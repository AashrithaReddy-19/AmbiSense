import asyncio
import logging
import shutil
import uuid
import importlib.util
import base64
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import torch
import cv2
import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session as DBSession

from . import crud, models, schemas
from .config import get_settings
from .database import Base, SessionLocal, engine, ensure_session_columns, get_db
from .services.report_generator import create_csv_report, create_pdf_report
from .services.semantic_search import search_analytics
from .services.video_processor import VideoProcessor
from .cv.face_landmarks import FaceLandmarkProcessor
from .cv.pose import PoseProcessor


settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=[logging.FileHandler(settings.log_dir / "ambisense.log", encoding="utf-8"), logging.StreamHandler()])
logger = logging.getLogger("ambisense")
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_session_columns()
    with SessionLocal() as db:
        if not db.scalar(select(models.Classroom.id).limit(1)):
            db.add(models.Classroom(name="Classroom A", total_students=40, total_seats=40))
            db.commit()
        for saved in db.scalars(select(models.RuntimeSetting)).all():
            if hasattr(settings, saved.key):
                setattr(settings, saved.key, saved.value)
    logger.info("AmbiSense started. Device: %s; Demo mode: %s", "CUDA" if torch.cuda.is_available() else "CPU", settings.demo_mode)
    yield


app = FastAPI(title="AmbiSense API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "device": "CUDA" if torch.cuda.is_available() else "CPU", "demo_mode": settings.demo_mode}


@app.get("/api/models/health")
def model_health():
    yolo_path = Path(settings.yolo_model)
    return {"device": "CUDA" if torch.cuda.is_available() else "CPU", "mode": "DEMO" if settings.demo_mode else "REAL", "models": [
        {"name": "YOLOv8", "loaded": importlib.util.find_spec("ultralytics") is not None, "path": yolo_path.name},
        {"name": "MediaPipe Face Landmarker", "loaded": importlib.util.find_spec("mediapipe") is not None and Path(settings.face_landmarker_model).exists(), "path": Path(settings.face_landmarker_model).name},
        {"name": "MediaPipe Pose Landmarker", "loaded": importlib.util.find_spec("mediapipe") is not None and Path(settings.pose_landmarker_model).exists(), "path": Path(settings.pose_landmarker_model).name},
        {"name": "ByteTrack", "loaded": importlib.util.find_spec("ultralytics") is not None, "path": "bytetrack.yaml"},
        {"name": "Sentence-BERT", "loaded": importlib.util.find_spec("sentence_transformers") is not None, "path": "local package"},
    ]}


def current_settings() -> dict:
    keys = ["expected_students", "total_seats", "yolo_confidence", "tracking_confidence", "process_every_n_frames", "ema_alpha", "ear_threshold", "drowsiness_duration", "yawn_threshold", "yawn_min_duration", "head_yaw_threshold", "head_pitch_threshold", "distraction_min_duration", "aggregation_interval", "privacy_mode", "show_overlays", "retention_days", "demo_mode"]
    return {key: getattr(settings, key) for key in keys}


@app.get("/api/settings")
def read_settings():
    return current_settings()


@app.put("/api/settings")
def update_settings(payload: schemas.RuntimeSettingsUpdate, db: DBSession = Depends(get_db)):
    values = payload.model_dump()
    for key, value in values.items():
        setattr(settings, key, value)
        row = db.get(models.RuntimeSetting, key)
        if row: row.value = value
        else: db.add(models.RuntimeSetting(key=key, value=value))
    db.commit()
    return {"status": "saved", "settings": current_settings(), "applies_to": "new processing jobs"}


@app.post("/api/sessions/start", response_model=schemas.SessionRead)
@app.post("/api/sessions", response_model=schemas.SessionRead)
def start_session(payload: schemas.SessionCreate, db: DBSession = Depends(get_db)):
    row = models.Session(name=payload.name, classroom_id=payload.classroom_id, source_type=payload.source_type, status="PROCESSING", started_at=datetime.utcnow())
    db.add(row); db.commit(); db.refresh(row)
    return row


@app.post("/api/sessions/{session_id}/stop", response_model=schemas.SessionRead)
def stop_session(session_id: int, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    row.status = "COMPLETED"; row.ended_at = datetime.utcnow(); db.commit(); db.refresh(row)
    return row


@app.get("/api/sessions", response_model=list[schemas.SessionRead])
def list_sessions(db: DBSession = Depends(get_db)):
    return db.scalars(select(models.Session).order_by(desc(models.Session.created_at))).all()


@app.get("/api/sessions/{session_id}", response_model=schemas.SessionRead)
def get_session(session_id: int, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    return row


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    if row.status == "PROCESSING": raise HTTPException(409, "Stop processing before deleting this session")
    paths = [Path(value) for value in (row.video_path, row.annotated_video_path) if value]
    for model in (models.StudentObservation, models.AnalyticsSnapshot, models.Event, models.Alert, models.Report):
        db.execute(delete(model).where(model.session_id == session_id))
    db.delete(row); db.commit()
    for path in paths:
        try:
            resolved = path.resolve()
            if path.is_file() and (resolved.is_relative_to(settings.upload_dir.resolve()) or resolved.is_relative_to(settings.report_dir.resolve())): path.unlink(missing_ok=True)
        except OSError: logger.warning("Could not remove session file %s", path.name)
    return {"status": "deleted", "session_id": session_id}


@app.post("/api/videos/upload", response_model=schemas.SessionRead)
@app.post("/api/uploads", response_model=schemas.SessionRead)
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...), name: str = Form("Uploaded classroom session"), db: DBSession = Depends(get_db)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES: raise HTTPException(415, "Supported formats: MP4, AVI, MOV, MKV")
    destination = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    written = 0; limit = settings.max_upload_mb * 1024 * 1024
    with destination.open("wb") as stream:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                stream.close(); destination.unlink(missing_ok=True); raise HTTPException(413, f"Upload exceeds {settings.max_upload_mb} MB")
            stream.write(chunk)
    row = models.Session(name=name, status="UPLOADED", processing_stage="UPLOADING", source_type="VIDEO", video_path=str(destination), analytics_mode="DEMO" if settings.demo_mode else "REAL")
    db.add(row); db.commit(); db.refresh(row)
    background_tasks.add_task(VideoProcessor(row.id, str(destination)).run)
    return row


@app.get("/api/sessions/{session_id}/analytics")
@app.get("/api/sessions/{session_id}/summary")
def analytics(session_id: int, db: DBSession = Depends(get_db)):
    try: return crud.session_summary(db, session_id)
    except LookupError as error: raise HTTPException(404, str(error)) from error


@app.get("/api/sessions/{session_id}/students")
def students(session_id: int, db: DBSession = Depends(get_db)):
    ids = db.scalars(select(models.StudentObservation.tracking_id).where(models.StudentObservation.session_id == session_id).distinct()).all()
    return {"session_id": session_id, "students": [{"tracking_id": item, "identity": "anonymous"} for item in ids]}


@app.get("/api/sessions/{session_id}/events")
def events(session_id: int, db: DBSession = Depends(get_db)):
    rows = db.scalars(select(models.Event).where(models.Event.session_id == session_id).order_by(models.Event.timestamp)).all()
    return [{"timestamp": row.timestamp, "tracking_id": row.tracking_id, "type": row.event_type, "severity": row.severity, "message": row.message} for row in rows]


@app.get("/api/sessions/{session_id}/video")
def session_video(session_id: int, annotated: bool = True, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    path_value = row.annotated_video_path if annotated else row.video_path
    if not path_value or not Path(path_value).exists(): raise HTTPException(404, "Requested video is not available")
    path = Path(path_value)
    return FileResponse(path, filename=path.name, media_type="video/mp4" if path.suffix.lower() == ".mp4" else "video/x-msvideo")


@app.get("/api/sessions/{session_id}/timeline")
@app.get("/api/sessions/{session_id}/metrics")
def timeline(session_id: int, db: DBSession = Depends(get_db)):
    rows = db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id == session_id).order_by(models.AnalyticsSnapshot.timestamp)).all()
    return [{"timestamp": row.timestamp, "student_count": row.student_count, "attendance": row.attendance, "attention": row.attention_score, "engagement": row.engagement_score, "fatigue": row.fatigue_score, "drowsiness": row.drowsiness_count, "yawning": row.yawning_count, "raised_hands": row.raised_hands, "distracted_students": row.distracted_students, "looking_down": row.looking_down_students, "looking_away": row.looking_away_students, "occupied_seats": row.occupied_seats, "empty_seats": row.empty_seats, "occupancy": row.occupied_seats, "mode": row.details.get("mode", "REAL")} for row in rows]


@app.get("/api/sessions/{session_id}/report")
def report(session_id: int, format: str = "csv", db: DBSession = Depends(get_db)):
    if not db.get(models.Session, session_id): raise HTTPException(404, "Session not found")
    if format not in {"csv", "pdf"}: raise HTTPException(400, "Report format must be csv or pdf")
    path = create_pdf_report(db, session_id) if format == "pdf" else create_csv_report(db, session_id)
    return FileResponse(path, filename=path.name, media_type="application/pdf" if format == "pdf" else "text/csv")


@app.get("/api/dashboard/summary")
@app.get("/api/dashboard")
def dashboard_summary(db: DBSession = Depends(get_db)):
    latest = db.scalar(select(models.AnalyticsSnapshot).order_by(desc(models.AnalyticsSnapshot.id)))
    sessions = db.scalars(select(models.Session)).all()
    latest_session = db.scalar(select(models.Session).order_by(desc(models.Session.id)))
    recent_events = db.scalars(select(models.Event).order_by(desc(models.Event.id)).limit(8)).all()
    return {"sessions": len(sessions), "active_sessions": sum(row.status == "PROCESSING" for row in sessions), "latest": None if not latest else {"students": latest.student_count, "attendance": latest.attendance, "attention": latest.attention_score, "engagement": latest.engagement_score, "fatigue": latest.fatigue_score, "drowsiness": latest.drowsiness_count, "yawning": latest.yawning_count, "raised_hands": latest.raised_hands, "empty_seats": latest.empty_seats, "occupancy": latest.occupied_seats}, "demo_mode": settings.demo_mode, "analytics_mode": latest_session.analytics_mode if latest_session else ("DEMO" if settings.demo_mode else "REAL"), "current_session": None if not latest_session else {"id": latest_session.id, "name": latest_session.name, "status": latest_session.status, "stage": latest_session.processing_stage}, "last_updated": None if not latest else latest.timestamp, "recent_events": [{"session_id": row.session_id, "timestamp": row.timestamp, "type": row.event_type, "severity": row.severity, "message": row.message} for row in recent_events]}


@app.get("/api/dashboard/trends")
def dashboard_trends(db: DBSession = Depends(get_db)):
    rows = db.scalars(select(models.AnalyticsSnapshot).order_by(desc(models.AnalyticsSnapshot.id)).limit(60)).all()
    return [{"timestamp": row.timestamp, "engagement": row.engagement_score, "attention": row.attention_score, "fatigue": row.fatigue_score, "student_count": row.student_count, "raised_hands": row.raised_hands, "drowsiness": row.drowsiness_count, "occupancy": row.occupied_seats} for row in reversed(rows)]


@app.get("/api/seat-configurations")
def seat_configurations(classroom_id: int = 1, db: DBSession = Depends(get_db)):
    rows = db.scalars(select(models.SeatConfiguration).where(models.SeatConfiguration.classroom_id == classroom_id)).all()
    return [{"id": row.id, "classroom_id": row.classroom_id, "name": row.name, "regions": row.regions} for row in rows]


@app.post("/api/seat-configurations")
def save_seat_configuration(payload: schemas.SeatConfigurationCreate, db: DBSession = Depends(get_db)):
    row = models.SeatConfiguration(classroom_id=payload.classroom_id, name=payload.name, regions=[region.model_dump() for region in payload.regions])
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "classroom_id": row.classroom_id, "name": row.name, "regions": row.regions}


@app.get("/api/classroom/occupancy")
def occupancy(db: DBSession = Depends(get_db)):
    latest = db.scalar(select(models.AnalyticsSnapshot).order_by(desc(models.AnalyticsSnapshot.id)))
    return {"total_seats": 40, "occupied": latest.occupied_seats if latest else 0, "empty": latest.empty_seats if latest else 40, "occupancy_rate": round((latest.occupied_seats if latest else 0) / 40 * 100, 2)}


@app.get("/api/classroom/engagement")
def engagement(db: DBSession = Depends(get_db)):
    latest = db.scalar(select(models.AnalyticsSnapshot).order_by(desc(models.AnalyticsSnapshot.id)))
    score = latest.engagement_score if latest else 0
    return {"estimated_engagement_index": score, "level": "LOW" if score < 40 else "MEDIUM" if score < 70 else "HIGH"}


@app.post("/api/search")
def search(payload: schemas.SearchRequest, db: DBSession = Depends(get_db)):
    return search_analytics(db, payload.query)


@app.get("/api/reports")
def reports(db: DBSession = Depends(get_db)):
    rows = db.scalars(select(models.Session).where(models.Session.status == "COMPLETED").order_by(desc(models.Session.created_at))).all()
    return [{**crud.session_summary(db, row.id), "name": row.name, "created_at": row.created_at, "analytics_mode": row.analytics_mode} for row in rows]


@app.get("/api/reports/{session_id}")
def report_alias(session_id: int, format: str = "pdf", db: DBSession = Depends(get_db)):
    return report(session_id, format, db)


@app.get("/api/session-comparison")
def compare_sessions(ids: str, db: DBSession = Depends(get_db)):
    selected = [int(value) for value in ids.split(",") if value.strip().isdigit()]
    if len(selected) < 2: raise HTTPException(400, "Select at least two session IDs")
    return [crud.session_summary(db, session_id) for session_id in selected]


@app.websocket("/ws/analytics/{session_id}")
@app.websocket("/ws/sessions/{session_id}")
async def websocket_analytics(websocket: WebSocket, session_id: int):
    await websocket.accept()
    try:
        while True:
            with SessionLocal() as db:
                row = db.scalar(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id == session_id).order_by(desc(models.AnalyticsSnapshot.timestamp)))
                session = db.get(models.Session, session_id)
                await websocket.send_json({"session_id": session_id, "status": session.status if session else "NOT_FOUND", "stage": session.processing_stage if session else "NOT_FOUND", "progress": session.progress if session else 0, "processed_frames": session.processed_frames if session else 0, "total_frames": session.total_frames if session else 0, "processing_speed": session.processing_speed if session else 0, "latency_ms": round(1000 / max(session.processing_speed, .01), 1) if session else 0, "eta_seconds": session.eta_seconds if session else 0, "analytics": None if not row else {"timestamp": row.timestamp, "student_count": row.student_count, "attendance": row.attendance, "attention": row.attention_score, "engagement": row.engagement_score, "drowsiness": row.drowsiness_count, "fatigue": row.fatigue_score, "yawning": row.yawning_count, "raised_hands": row.raised_hands, "distracted_students": row.distracted_students, "occupied_seats": row.occupied_seats, "empty_seats": row.empty_seats, "events": [], "mode": row.details.get("mode", "REAL")}})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)


@app.websocket("/ws/live/{session_id}")
async def websocket_live_frames(websocket: WebSocket, session_id: int):
    """Receive browser JPEG frames and return persisted anonymous CV analytics."""
    await websocket.accept()
    with SessionLocal() as db:
        session = db.get(models.Session, session_id)
        if not session:
            await websocket.send_json({"error": "Session not found"}); await websocket.close(code=1008); return
        session.status = "PROCESSING"; session.processing_stage = "LIVE_ANALYSIS"; session.analytics_mode = "REAL"; db.commit()
    from ultralytics import YOLO
    detector = YOLO(settings.yolo_model)
    face_processor = FaceLandmarkProcessor(Path(settings.face_landmarker_model))
    pose_processor = PoseProcessor(Path(settings.pose_landmarker_model))
    processor = VideoProcessor(session_id, "", settings)
    started = time.perf_counter(); frame_count = 0
    try:
        while True:
            encoded = await websocket.receive_bytes()
            frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                await websocket.send_json({"error": "Invalid camera frame"}); continue
            timestamp = time.perf_counter() - started; frame_count += 1; timestamp_ms = int(timestamp * 1000)
            result = detector.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml", conf=settings.yolo_confidence, device=processor.device, verbose=False)[0]
            faces = face_processor.process(frame, timestamp_ms); poses = pose_processor.process(frame, timestamp_ms)
            with SessionLocal() as db:
                observations = processor._observations(db, result, faces, poses, timestamp)
                processor._aggregate(db, timestamp, observations)
                session = db.get(models.Session, session_id); session.processed_frames = frame_count; session.processing_speed = round(frame_count / max(timestamp, .001), 2); db.commit()
            annotated = frame.copy()
            if settings.show_overlays:
                for observation in observations: processor._draw(annotated, observation)
            ok, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
            count = len(observations); attention = sum(row["attention_score"] for row in observations) / count if count else 0
            await websocket.send_json({"timestamp": round(timestamp, 2), "student_count": count, "attention": round(attention, 2), "raised_hands": sum(row["raised_hand"] for row in observations), "drowsiness": sum(row["drowsiness"] for row in observations), "yawning": sum(row["yawning"] for row in observations), "processing_fps": round(frame_count / max(timestamp, .001), 2), "latency_ms": round(1000 / max(frame_count / max(timestamp, .001), .01), 1), "annotated_image": base64.b64encode(jpeg).decode() if ok else None, "privacy_mode": settings.privacy_mode})
    except WebSocketDisconnect:
        logger.info("Live camera disconnected for session %s", session_id)
    finally:
        face_processor.close(); pose_processor.close()
