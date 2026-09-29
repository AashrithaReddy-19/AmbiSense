import asyncio
import logging
import re
from collections import Counter
from types import SimpleNamespace
import shutil
import uuid
import importlib.util
import base64
import time
import csv
import io
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import torch
import cv2
import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response as HttpResponse, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import case, delete, desc, func, or_, select, text
from sqlalchemy.orm import Session as DBSession

from . import crud, models, schemas
from .timeutil import utc_iso_z, utc_now_naive
from .config import get_settings
from .database import Base, SessionLocal, engine, ensure_session_columns, get_db
from .services.report_generator import create_csv_report, create_metrics_csv_report, create_pdf_report, create_transcript_export
from .services.semantic_search import search_analytics
from .services.video_processor import VideoProcessor
from .services.cleanup import cleanup_expired_transcripts, cleanup_test_sessions, preview_test_session_cleanup
from .services.activity_context import ACTIVITY_CONTEXTS
from .services.heatmaps import aggregate_region_heatmap
from .cv.face_landmarks import FaceLandmarkProcessor
from .cv.pose import PoseProcessor
from .cv.regions import region_summary
from .cv.quality import assess_frame_quality
from .auth import Principal, authorize_http_request, bulk_accessible_sessions, can_access_course, can_access_note, can_access_session, create_token, hash_password, principal, require, resolve_principal, verify_password
from .services.priority4 import CANONICAL_METRIC_NAMES, aggregate_dashboard, compare as compare_evidence, evidence_for_sessions, generate_alerts, session_evidence, trend_buckets
from .metrics import as_metric_availability, build_metric, frame_quality_metric, metric_envelope
from .errors import RequestIdFilter, error_response, install_error_handling, structured_error as _structured_error
from .services import retention as retention_service
from .services.audio_capabilities import audio_capabilities
from .auth import PERMISSIONS as ROLE_PERMISSIONS
from .services.jobs import claim_retry, get_job_runner, live_connection_closed, live_connection_opened, recover_interrupted_jobs, stale_job_report, upsert_report
from .services.layout_validation import validate_layout
from .services.rate_limit import limit as rate_limit
from .services.settings_catalog import CATALOG, settings_catalog
from .services.startup_checks import ConfigIssue, enforce_settings, readiness
from .evaluation import validation_status as evaluation_validation_status


settings = get_settings()
_log_handlers = [logging.FileHandler(settings.log_dir / "ambisense.log", encoding="utf-8"), logging.StreamHandler()]
for _handler in _log_handlers: _handler.addFilter(RequestIdFilter())
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s", handlers=_log_handlers)
logger = logging.getLogger("ambisense")
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}
ALLOWED_VIDEO_MIME_TYPES = {"video/mp4", "video/quicktime", "video/x-msvideo", "video/avi", "video/x-matroska", "application/octet-stream"}


def _probe_uploaded_video(path: Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise _structured_error(422, "VIDEO_DECODING_FAILED", "The video could not be decoded. The codec may be unsupported.")
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, _ = capture.read()
        if not ok or frames <= 0 or fps <= 0 or width <= 0 or height <= 0:
            raise _structured_error(422, "VIDEO_DECODING_FAILED", "No decodable video frames were found.")
        duration = frames / fps
        if duration > settings.max_video_duration_minutes * 60:
            raise _structured_error(413, "VIDEO_TOO_LONG", f"Video duration exceeds {settings.max_video_duration_minutes} minutes.")
        return {"frames": frames, "fps": fps, "duration": duration}
    finally:
        capture.release()

_FILENAME_UNSAFE = re.compile(r"[^\w.\- ()\[\]]", re.UNICODE)


def sanitize_filename(value: str | None, fallback: str = "upload") -> str:
    """Keep only the base name, drop control/path characters and cap the length. Used for display metadata only; storage names are always random."""
    base = (value or "").replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"\.{2,}", ".", _FILENAME_UNSAFE.sub("_", base)).strip(" .")
    return (cleaned or fallback)[:200]


def _managed_file(path_value: str | None) -> Path | None:
    """Resolve a stored artifact path only if it exists inside the managed upload/report directories."""
    if not path_value: return None
    path = Path(path_value)
    return path if path.is_file() and retention_service.is_managed_path(path, settings) else None


def auth_permissions(role: str) -> set:
    return ROLE_PERMISSIONS.get(role, set())


def _apply_data_source(statement, data_source: str):
    """REAL/DEMO exclude test-flagged sessions; TEST is exactly the test-flagged sessions; ALL is unfiltered."""
    source = data_source.upper()
    if source == "REAL": return statement.where(models.Session.analytics_mode == "REAL", models.Session.is_test.is_(False))
    if source == "DEMO": return statement.where(models.Session.analytics_mode == "DEMO", models.Session.is_test.is_(False))
    if source == "TEST": return statement.where(models.Session.is_test.is_(True))
    return statement


def _accessible_sessions(db:DBSession,user:Principal,statement=None):
    rows=db.scalars(select(models.Session) if statement is None else statement).all()
    return bulk_accessible_sessions(db,user,rows)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _app.state.config_issues = enforce_settings(settings)  # refuses to start on ERROR-level issues
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
    async def cleanup_loop():
        # Wait one interval first: even when enabled, a restart never rewrites history immediately.
        while True:
            await asyncio.sleep(max(60,settings.test_session_cleanup_interval_minutes*60))
            try:
                with SessionLocal() as cleanup_db:
                    cleanup_test_sessions(cleanup_db,settings)
                    cleanup_expired_transcripts(cleanup_db,settings)
            except Exception: logger.exception("Scheduled cleanup failed")
    cleanup_task=asyncio.create_task(cleanup_loop()) if settings.scheduled_cleanup_enabled else None
    logger.info("Scheduled cleanup: %s. Startup makes no changes to existing sessions.", "ENABLED (first run after one interval)" if cleanup_task else "disabled")
    yield
    if cleanup_task: cleanup_task.cancel()


app = FastAPI(title="AmbiSense API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID", "X-Total-Count", "Retry-After"])
if settings.trusted_host_list != ["*"]: app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)

@app.middleware("http")
async def authorization_boundary(request,call_next):
    try: authorize_http_request(request)
    except HTTPException as error:return error_response(error.status_code,error.detail)
    return await call_next(request)


install_error_handling(app)  # registered last so the request-ID middleware is outermost


@app.get("/api/health")
def health():
    return {"status": "ok", "device": "CUDA" if torch.cuda.is_available() else "CPU", "demo_mode": settings.demo_mode, "max_upload_mb": settings.max_upload_mb, "max_video_duration_minutes": settings.max_video_duration_minutes, "allowed_video_extensions": sorted(ALLOWED_VIDEO_SUFFIXES)}

@app.post("/api/v1/auth/login", dependencies=[Depends(rate_limit("login"))])
def login(payload:schemas.LoginRequest,db:DBSession=Depends(get_db)):
    user=db.scalar(select(models.User).where(models.User.email==payload.email.lower()))
    if not user or not user.active or not verify_password(payload.password,user.password_hash):raise HTTPException(401,"Invalid credentials")
    auth_settings=get_settings();return {"access_token":create_token(user,auth_settings),"token_type":"bearer","expires_in":auth_settings.auth_access_token_expire_minutes*60,"user":{"id":user.id,"email":user.email,"display_name":user.display_name,"role":user.role}}

@app.get("/api/v1/auth/me")
def auth_me(user:Principal=Depends(principal)):return {"id":user.id,"email":user.email,"display_name":getattr(user,"display_name",None) or user.email,"role":user.role,"auth_enabled":settings.auth_enabled}

@app.post("/api/v1/auth/logout")
def logout(db:DBSession=Depends(get_db),user:Principal=Depends(principal)):
    if user.id is not None:
        row=db.get(models.User,user.id);row.token_version+=1;db.commit()
    return {"status":"logged_out"}


@app.get("/api/v1/system/pipeline-health")
def pipeline_health(session_id: int | None = None, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id) if session_id else db.scalar(select(models.Session).order_by(desc(models.Session.id)))
    active = bool(row and row.status in {"INITIALIZING", "PROCESSING", "FINALIZING"})
    return {"session_id": row.id if row else None, "camera_permission": "BROWSER_MANAGED", "camera_connected": bool(row and row.source_type == "LIVE" and active), "frame_capture_active": active, "frames_transmitted": row.processed_frames if row else 0, "backend_connection": "CONNECTED", "backend_receiving_frames": bool(row and row.processed_frames > 0), "decoder_state": "ACTIVE" if active else "IDLE", "yolo_model_state": "ENABLED" if importlib.util.find_spec("ultralytics") else "MODEL_DISABLED", "face_model_state": "ENABLED" if Path(settings.face_landmarker_model).exists() else "MODEL_DISABLED", "pose_model_state": "ENABLED" if Path(settings.pose_landmarker_model).exists() else "MODEL_DISABLED", "tracker_state": "ACTIVE" if active else "IDLE", "inference_active": active, "aggregator_active": active, "websocket_connected": None, "database_write_state": "AVAILABLE", "reportable_analytics_available": bool(row and db.scalar(select(models.AnalyticsSnapshot.id).where(models.AnalyticsSnapshot.session_id == row.id).limit(1)))}


@app.get("/api/ready")
def ready(db: DBSession = Depends(get_db)):
    """Readiness (database, models, writable storage, job runner). 503 when any check fails."""
    result = readiness(db, settings, get_job_runner(settings))
    return JSONResponse(result, status_code=200 if result["status"] == "ready" else 503)


def _alembic_revision(db) -> str | None:
    try: return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception: return None


@app.get("/api/v1/system/diagnostics")
def development_diagnostics(request: Request, db: DBSession = Depends(get_db)):
    """Operational diagnostics for administrators. Never returns secrets, tokens, raw SQL, private data or filesystem paths."""
    if settings.log_level.upper() not in {"DEBUG", "INFO"}: raise HTTPException(404, "Not found")
    active=db.scalar(select(models.Session).where(models.Session.status.in_(["DECODING","PROCESSING","AGGREGATING","GENERATING_REPORT","INITIALIZING"])).order_by(desc(models.Session.id)))
    latest_failed=db.scalar(select(models.Session).where(models.Session.status=="FAILED").order_by(desc(models.Session.id)))
    runner=get_job_runner(settings).health(db)
    issues=[issue.as_dict() for issue in getattr(request.app.state,"config_issues",[]) or []]
    return {"frontend_api_url":"/api","websocket_url":"/ws/live/{session_id}","backend_health":"OK","request_id":getattr(request.state,"request_id",None),
        "database":{"dialect":engine.dialect.name,"alembic_revision":_alembic_revision(db)},
        "worker":{"mode":runner["mode"],"healthy":runner["healthy"],"queue_depth":runner.get("queue_depth",0),"stale_jobs":runner.get("stale_jobs",0),"durable":runner.get("durable",False)},
        "readiness":readiness(db,settings,get_job_runner(settings)),
        "configuration":{"issues":issues,"auth_enabled":settings.auth_enabled,"demo_mode":settings.demo_mode,"rate_limit_enabled":settings.rate_limit_enabled,"rate_limit_backend":settings.rate_limit_backend},
        "models":{"yolo":Path(settings.yolo_model).name,"face":Path(settings.face_landmarker_model).name,"pose":Path(settings.pose_landmarker_model).name},
        "active_session_id":active.id if active else None,"frames_received":active.processed_frames if active else 0,"frames_processed":active.processed_frames if active else 0,
        "latest_job_error":None if not latest_failed else {"session_id":latest_failed.id,"job_id":latest_failed.job_id,"failure_code":latest_failed.failure_code,"message":(latest_failed.error or "")[:200]}}


@app.get("/api/v1/system/jobs/stale")
def stale_jobs(db: DBSession = Depends(get_db), user: Principal = Depends(require("user:manage"))):
    """Read-only preview for administrators: sessions that claim to be running but that no worker is processing."""
    return stale_job_report(db, get_job_runner(settings))


@app.post("/api/v1/system/jobs/recover")
def recover_jobs(confirm: bool = False, session_ids: list[int] | None = Query(default=None), db: DBSession = Depends(get_db), user: Principal = Depends(require("user:manage"))):
    """Explicit admin action: mark stale video jobs as FAILED (retryable), optionally only the listed sessions. Never run automatically.
    Sessions owned by a running worker, and interrupted live captures, are never changed."""
    if not confirm: raise _structured_error(400,"CONFIRMATION_REQUIRED","Set confirm=true to mark interrupted jobs as FAILED. Use GET /api/v1/system/jobs/stale to preview them.")
    recovered=recover_interrupted_jobs(db,session_ids=session_ids,actor_user_id=user.id,runner=get_job_runner(settings))
    return {"recovered_session_ids":recovered,"count":len(recovered),"requested_session_ids":session_ids}


@app.get("/api/models/health")
def model_health():
    yolo_path = Path(settings.yolo_model)
    return {"device": "CUDA" if torch.cuda.is_available() else "CPU", "mode": "DEMO" if settings.demo_mode else "REAL", "models": [
        {"name": "YOLOv8", "loaded": importlib.util.find_spec("ultralytics") is not None, "path": yolo_path.name},
        {"name": "MediaPipe Face Landmarker", "loaded": importlib.util.find_spec("mediapipe") is not None and Path(settings.face_landmarker_model).exists(), "path": Path(settings.face_landmarker_model).name},
        {"name": "MediaPipe Pose Landmarker", "loaded": importlib.util.find_spec("mediapipe") is not None and Path(settings.pose_landmarker_model).exists(), "path": Path(settings.pose_landmarker_model).name},
        {"name": "ByteTrack", "loaded": importlib.util.find_spec("ultralytics") is not None, "path": "bytetrack.yaml"},
        {"name": "Sentence-BERT", "loaded": importlib.util.find_spec("sentence_transformers") is not None, "path": "local package"},
        {"name": "FFmpeg audio extraction", "loaded": shutil.which("ffmpeg") is not None, "path": shutil.which("ffmpeg") or "MODEL_UNAVAILABLE"},
        {"name": "Faster Whisper", "loaded": importlib.util.find_spec("faster_whisper") is not None, "path": settings.transcription_model},
    ]}


def current_settings() -> dict:
    keys = ["expected_students", "total_seats", "yolo_confidence", "tracking_confidence", "process_every_n_frames", "ema_alpha", "ear_threshold", "drowsiness_duration", "yawn_threshold", "yawn_min_duration", "head_yaw_threshold", "head_pitch_threshold", "distraction_min_duration", "aggregation_interval", "privacy_mode", "show_overlays", "retention_days", "demo_mode", "audio_analytics_enabled", "transcription_provider", "transcription_model", "transcription_language", "transcript_retention_days", "transcript_retention_enabled", "diarization_provider"]
    return {key: getattr(settings, key) for key in keys}


@app.get("/api/settings")
def read_settings():
    return current_settings()


@app.put("/api/settings")
def update_settings(payload: schemas.RuntimeSettingsUpdate, confirm_risky: bool = False, db: DBSession = Depends(get_db), user: Principal = Depends(require("user:manage"))):
    """Validated update of runtime-editable settings. Risky changes need confirm_risky=true; every change is audited."""
    values = payload.model_dump()
    before = current_settings()
    changes = {key: {"from": before[key], "to": value} for key, value in values.items() if key in before and before[key] != value}
    risky_keys = {entry["key"] for entry in CATALOG if entry["risky"]}
    risky_changed = sorted(key for key in changes if key in risky_keys)
    if risky_changed and not confirm_risky:
        raise _structured_error(409, "RISKY_CHANGE_REQUIRES_CONFIRMATION", "These settings change analytics or privacy behaviour for new jobs. Confirm to apply.", {"keys": risky_changed})
    for key, value in values.items():
        setattr(settings, key, value)
        row = db.get(models.RuntimeSetting, key)
        if row: row.value = value
        else: db.add(models.RuntimeSetting(key=key, value=value))
    if changes: _audit(db, user, "SETTINGS_UPDATED", "SETTINGS", None, {"changes": changes})
    db.commit()
    return {"status": "saved", "settings": current_settings(), "applies_to": "new processing jobs", "changes": changes}


@app.get("/api/v1/settings/catalog")
def settings_catalog_endpoint():
    """Grouped catalogue of real, supported settings with units, ranges, restart flags and read-only environment values. Never includes secrets."""
    return settings_catalog(settings)


@app.get("/api/v1/audio/capabilities")
def audio_capabilities_endpoint():
    return audio_capabilities(settings)


@app.get("/api/v1/evaluation/status")
def evaluation_status():
    """Honest validation status: no accuracy or fairness result exists until a consented, labelled evaluation is run."""
    return evaluation_validation_status()


@app.post("/api/sessions/start", response_model=schemas.SessionRead)
@app.post("/api/sessions", response_model=schemas.SessionRead)
def start_session(payload: schemas.SessionCreate, db: DBSession = Depends(get_db),user:Principal=Depends(require("session:upload"))):
    if payload.classroom_id and not can_access_session(db,user,models.Session(classroom_id=payload.classroom_id)):raise HTTPException(403,"Classroom access denied")
    row = models.Session(name=payload.name, classroom_id=payload.classroom_id, source_type=payload.source_type, activity_context=payload.activity_context, status="CREATED", processing_stage="CREATED", is_test=payload.is_test or payload.name.lower().startswith(("api test", "acceptance", "websocket schema test")))
    db.add(row); db.commit(); db.refresh(row)
    return row


@app.post("/api/sessions/{session_id}/stop", response_model=schemas.SessionRead)
def stop_session(session_id: int, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    row.status = "STOPPED"; row.processing_stage = "STOPPED"; row.ended_at = utc_now_naive(); db.commit(); db.refresh(row)
    return row


@app.get("/api/sessions", response_model=list[schemas.SessionRead])
def list_sessions(db: DBSession = Depends(get_db),user:Principal=Depends(require("session:view"))):
    return _accessible_sessions(db,user,select(models.Session).order_by(desc(models.Session.created_at)))


@app.get("/api/v1/sessions")
def list_sessions_v1(q: str | None = None, status: str | None = None, mode: str | None = None, classroom_id: int | None = None, course_id: int | None = None, activity_context: str | None = None, start_date: datetime | None = None, end_date: datetime | None = None, minimum_coverage: float | None = None, archived: bool = False, include_tests: bool = False, sort: str = "newest", page: int = 1, page_size: int = 25, db: DBSession = Depends(get_db),user:Principal=Depends(require("session:view"))):
    if start_date and end_date and start_date>end_date: raise _structured_error(400,"INVALID_DATE_RANGE","start_date must not be after end_date.")
    if minimum_coverage is not None and not (0.0<=minimum_coverage<=1.0): raise _structured_error(400,"INVALID_COVERAGE","minimum_coverage must be between 0.0 and 1.0.")
    page=max(1,page); page_size=max(1,min(100,page_size)); statement=select(models.Session).where(models.Session.archived==archived)
    if not include_tests: statement=statement.where(models.Session.is_test.is_(False))
    if q: statement=statement.where(or_(models.Session.name.ilike(f"%{q}%"),models.Session.source_type.ilike(f"%{q}%")))
    if status: statement=statement.where(models.Session.status==status.upper())
    if mode: statement=statement.where(models.Session.analytics_mode==mode.upper())
    if classroom_id: statement=statement.where(models.Session.classroom_id==classroom_id)
    if course_id: statement=statement.where(models.Session.course_id==course_id)
    if activity_context: statement=statement.where(models.Session.activity_context==activity_context)
    if start_date: statement=statement.where(models.Session.created_at>=start_date)
    if end_date: statement=statement.where(models.Session.created_at<=end_date)
    order=models.Session.created_at.asc() if sort=="oldest" else models.Session.created_at.desc()
    accessible=_accessible_sessions(db,user,statement.order_by(order))
    if minimum_coverage is not None and accessible:
        # Session-level coverage is the fraction of a session's processed
        # snapshots that had at least one detected person (see
        # /api/v1/dashboard/overview for the same definition). Computed in
        # one grouped query for every candidate session, never one query
        # per session, so this filter stays bounded regardless of result size.
        ids=[row.id for row in accessible]
        coverage_by_session:dict[int,float]={}
        for session_id,total_count,present_count in db.execute(select(models.AnalyticsSnapshot.session_id,func.count(),func.sum(case((models.AnalyticsSnapshot.student_count>0,1),else_=0))).where(models.AnalyticsSnapshot.session_id.in_(ids)).group_by(models.AnalyticsSnapshot.session_id)).all():
            if total_count: coverage_by_session[session_id]=(present_count or 0)/total_count
        accessible=[row for row in accessible if coverage_by_session.get(row.id,0.0)>=minimum_coverage]
    total=len(accessible);rows=accessible[(page-1)*page_size:page*page_size]
    return {"items":[schemas.SessionRead.model_validate(row) for row in rows],"page":page,"page_size":page_size,"total":total,"pages":max(1,(total+page_size-1)//page_size)}


@app.post("/api/v1/sessions/{session_id}/archive")
def archive_session(session_id: int, archived: bool = True, db: DBSession = Depends(get_db)):
    row=db.get(models.Session,session_id)
    if not row: raise HTTPException(404,"Session not found")
    if row.status in {"INITIALIZING","PROCESSING","FINALIZING"}: raise HTTPException(409,"Active sessions cannot be archived")
    row.archived=archived; db.commit(); return {"session_id":session_id,"archived":row.archived}


@app.post("/api/v1/sessions/bulk-archive-tests")
def bulk_archive_tests(db: DBSession = Depends(get_db),user:Principal=Depends(require("session:upload"))):
    rows=_accessible_sessions(db,user,select(models.Session).where(models.Session.is_test.is_(True),models.Session.archived.is_(False)))
    for row in rows: row.archived=True
    db.commit(); return {"archived":len(rows)}


@app.post("/api/v1/sessions/bulk-archive")
def bulk_archive(payload: schemas.BulkArchiveRequest, db: DBSession = Depends(get_db),user:Principal=Depends(require("session:upload"))):
    ids=sorted(set(payload.session_ids)); rows=db.scalars(select(models.Session).where(models.Session.id.in_(ids))).all(); found={row.id for row in rows}; archived=[]; skipped=[]
    if any(not can_access_session(db,user,row) for row in rows):raise HTTPException(403,"Session access denied")
    for row in rows:
        if row.status in {"INITIALIZING","PROCESSING","FINALIZING"}: skipped.append({"id":row.id,"reason":"ACTIVE"}); continue
        if not row.archived: row.archived=True
        archived.append(row.id)
    db.commit(); return {"requested":ids,"archived":archived,"skipped":skipped,"not_found":sorted(set(ids)-found)}


@app.get("/api/v1/system/cleanup-test-sessions/preview")
def preview_test_cleanup(db: DBSession = Depends(get_db)):
    """Read-only: the sessions a test-session cleanup would archive or delete right now."""
    return preview_test_session_cleanup(db,settings)


@app.post("/api/v1/system/cleanup-test-sessions")
def run_test_cleanup(confirm: bool = False, db: DBSession = Depends(get_db)):
    """Explicit administrator action. Preview first; nothing is changed without confirm=true."""
    if not confirm: raise _structured_error(400,"CONFIRMATION_REQUIRED","Set confirm=true to run test-session cleanup. Use /cleanup-test-sessions/preview to see what would change.")
    return cleanup_test_sessions(db,settings,manual=True)


@app.get("/api/v1/system/cleanup-audit")
def cleanup_audit(limit: int = 50, db: DBSession = Depends(get_db)):
    rows=db.scalars(select(models.CleanupAudit).order_by(desc(models.CleanupAudit.id)).limit(max(1,min(200,limit)))).all()
    return [{"run_id":r.run_id,"session_id":r.session_id,"action":r.action,"result":r.result,"details":r.details,"created_at":r.created_at} for r in rows]


@app.get("/api/sessions/{session_id}", response_model=schemas.SessionRead)
def get_session(session_id: int, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    return row


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, confirm: bool = False, db: DBSession = Depends(get_db), user: Principal = Depends(require("session:upload"))):
    """Permanently delete a session, all dependent rows and its managed artifacts. Requires confirm=true and writes an audit entry."""
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    if row.status in retention_service.ACTIVE_STATES: raise _structured_error(409, "SESSION_ACTIVE", "Stop processing before deleting this session.")
    if not confirm: raise _structured_error(400, "CONFIRMATION_REQUIRED", "Deleting a session is permanent. Repeat the request with confirm=true.")
    return retention_service.delete_session(db, row, settings, user.id)


@app.get("/api/v1/sessions/{session_id}/artifacts")
def session_artifacts(session_id: int, db: DBSession = Depends(get_db)):
    """Artifacts that really exist on disk for this session (never guessed), with authorized download URLs."""
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    items = []

    def add(kind, label, path, url, media_type):
        if path is not None: items.append({"kind": kind, "label": label, "filename": path.name, "size_bytes": path.stat().st_size, "media_type": media_type, "url": url})

    add("source_video", "Original video", _managed_file(row.video_path), f"/api/sessions/{session_id}/video?annotated=false", "video/mp4")
    add("annotated_video", "Annotated video", _managed_file(row.annotated_video_path), f"/api/sessions/{session_id}/video?annotated=true", "video/mp4")
    labels = {"pdf": ("Report (PDF)", "application/pdf"), "csv": ("Report (CSV)", "text/csv"), "metrics": ("Metrics (CSV)", "text/csv")}
    for report_row in db.scalars(select(models.Report).where(models.Report.session_id == session_id).order_by(models.Report.format)).all():
        label, media = labels.get(report_row.format, (report_row.format, "application/octet-stream"))
        add(f"report_{report_row.format}", label, _managed_file(report_row.path), f"/api/sessions/{session_id}/report?format={report_row.format}", media)
    for extension, media in (("json", "application/json"), ("csv", "text/csv"), ("txt", "text/plain")):
        add(f"transcript_{extension}", f"Transcript export ({extension.upper()})", _managed_file(str(settings.report_dir / f"transcript_{session_id}.{extension}")), f"/api/v1/sessions/{session_id}/transcript/export?format={extension}", media)
    return {"session_id": session_id, "status": row.status, "artifacts": items}


@app.delete("/api/v1/sessions/{session_id}/artifacts")
def delete_session_artifacts(session_id: int, kinds: str, confirm: bool = False, db: DBSession = Depends(get_db), user: Principal = Depends(require("session:upload"))):
    """Delete stored files (source/annotated video, reports, audio) while keeping analytics evidence. Requires confirm=true."""
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    if row.status in retention_service.ACTIVE_STATES: raise _structured_error(409, "SESSION_ACTIVE", "Stop processing before deleting artifacts.")
    requested = {value.strip() for value in kinds.split(",") if value.strip()}
    if not requested or not requested <= retention_service.ARTIFACT_KINDS: raise _structured_error(400, "INVALID_ARTIFACT_KIND", f"kinds must be a comma-separated subset of: {', '.join(sorted(retention_service.ARTIFACT_KINDS))}.")
    if not confirm: raise _structured_error(400, "CONFIRMATION_REQUIRED", "Deleting artifacts is permanent. Repeat the request with confirm=true.")
    return retention_service.delete_artifacts(db, row, requested, settings, user.id)


@app.get("/api/v1/retention/policy")
def retention_policy(db: DBSession = Depends(get_db)):
    return {**retention_service.retention_preview(db, settings), "transcripts": {"enabled": settings.transcript_retention_enabled, "days": settings.transcript_retention_days}, "test_sessions": {"scheduled_enabled": settings.scheduled_cleanup_enabled, "cleanup_enabled": settings.test_session_cleanup_enabled, "action": settings.test_session_cleanup_action, "age_hours": settings.test_session_cleanup_age_hours}}


@app.post("/api/v1/retention/sessions/run")
def run_session_retention(confirm: bool = False, db: DBSession = Depends(get_db), user: Principal = Depends(require("user:manage"))):
    """Archive (never delete) sessions older than the retention period. Requires confirm=true."""
    if not confirm: raise _structured_error(400, "CONFIRMATION_REQUIRED", "Set confirm=true to archive the sessions listed by GET /api/v1/retention/policy.")
    return retention_service.apply_retention(db, settings, user.id)


@app.post("/api/videos/upload", response_model=schemas.SessionRead, dependencies=[Depends(rate_limit("upload"))])
@app.post("/api/uploads", response_model=schemas.SessionRead, dependencies=[Depends(rate_limit("upload"))])
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...), name: str = Form("Uploaded classroom session"), classroom_id: int | None = Form(None), activity_context: str = Form("LECTURE"), course_id: int | None = Form(None), db: DBSession = Depends(get_db)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES: raise _structured_error(415, "UNSUPPORTED_VIDEO_FORMAT", "Supported formats: MP4, AVI, MOV, MKV.")
    if file.content_type and file.content_type.lower() not in ALLOWED_VIDEO_MIME_TYPES: raise _structured_error(415, "UNSUPPORTED_MIME_TYPE", "The uploaded MIME type is not a supported video format.")
    name = name.strip()
    if not 1 <= len(name) <= 160: raise _structured_error(422, "INVALID_SESSION_NAME", "Session name must be between 1 and 160 characters.")
    activity_context = activity_context.strip().upper()
    if activity_context not in ACTIVITY_CONTEXTS: raise _structured_error(422, "INVALID_ACTIVITY_CONTEXT", f"Activity context must be one of: {', '.join(ACTIVITY_CONTEXTS)}.")
    if classroom_id is not None and not db.get(models.Classroom, classroom_id): raise _structured_error(404, "CLASSROOM_NOT_FOUND", "Classroom not found.")
    if course_id is not None and not db.get(models.Course, course_id): raise _structured_error(404, "COURSE_NOT_FOUND", "Course not found.")
    destination = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    written = 0; limit = settings.max_upload_mb * 1024 * 1024
    try:
        with destination.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit: raise _structured_error(413, "FILE_TOO_LARGE", f"Upload exceeds {settings.max_upload_mb} MB.")
                stream.write(chunk)
        if written == 0: raise _structured_error(422, "EMPTY_FILE", "The uploaded file is empty.")
        metadata = _probe_uploaded_video(destination)
        job_id = uuid.uuid4().hex
        mode = "DEMO" if settings.demo_mode else "REAL"
        row = models.Session(name=name, status="QUEUED", processing_stage="QUEUED", source_type="VIDEO", source_filename=sanitize_filename(file.filename or name), video_path=str(destination), job_id=job_id, data_source=mode, analytics_mode=mode, duration=metadata["duration"], fps=metadata["fps"], total_frames=metadata["frames"], classroom_id=classroom_id, course_id=course_id, activity_context=activity_context)
        db.add(row); db.commit(); db.refresh(row)
    except BaseException:
        # Any failure (validation, decode, size, database) must not leave an orphan upload behind.
        destination.unlink(missing_ok=True); db.rollback()
        raise
    logger.info("[JOB] queued session_id=%s job_id=%s", row.id, job_id)
    get_job_runner(settings).dispatch(row.id, str(destination), settings, background_tasks)
    return row


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, db: DBSession = Depends(get_db)):
    row = db.scalar(select(models.Session).where(models.Session.job_id == job_id))
    if not row: raise HTTPException(404, "Processing job not found")
    return {"job_id": row.job_id, "session_id": row.id, "status": row.status, "stage": row.processing_stage, "progress": row.progress, "processed_frames": row.processed_frames, "total_frames": row.total_frames, "processing_speed": row.processing_speed, "eta_seconds": row.eta_seconds, "error": row.error, "failure_code": row.failure_code, "report_ready": row.status == "COMPLETED" and bool(db.scalar(select(models.Report.id).where(models.Report.session_id == row.id)))}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, background_tasks: BackgroundTasks, db: DBSession = Depends(get_db)):
    row = db.scalar(select(models.Session).where(models.Session.job_id == job_id))
    if not row: raise _structured_error(404, "JOB_NOT_FOUND", "Processing job not found.")
    if row.status != "FAILED": raise _structured_error(409, "JOB_NOT_RETRYABLE", "Only failed jobs can be retried.")
    if not row.video_path or not Path(row.video_path).exists(): raise _structured_error(409, "SOURCE_VIDEO_UNAVAILABLE", "The retained source video is unavailable.")
    # Atomic FAILED -> QUEUED transition: concurrent retries cannot both win, so a job is never queued twice.
    if not claim_retry(db, row.id): raise _structured_error(409, "JOB_NOT_RETRYABLE", "This job was already retried or is no longer failed.")
    db.refresh(row)
    logger.info("[JOB] retry queued session_id=%s job_id=%s retry=%s", row.id, row.job_id, row.retry_count)
    get_job_runner(settings).dispatch(row.id, row.video_path, settings, background_tasks)
    return {"job_id": row.job_id, "session_id": row.id, "status": row.status, "retry_count": row.retry_count}


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
    return [{"id":row.id,"timestamp": row.timestamp,"end_timestamp":row.end_timestamp,"tracking_id": row.tracking_id, "type": row.event_type, "severity": row.severity, "message": row.message,"confidence":row.confidence,"region_id":row.region_id,"affected_tracks":row.affected_tracks,"evidence_coverage":row.evidence_coverage,"review_state":row.review_state,"reviewer_note":row.reviewer_note,"included_in_report":row.included_in_report} for row in rows]


@app.put("/api/v1/events/{event_id}/review")
def review_event(event_id: int, payload: schemas.EventReviewUpdate, db: DBSession = Depends(get_db)):
    row=db.get(models.Event,event_id)
    if not row: raise HTTPException(404,"Event not found")
    row.review_state=payload.review_state; row.reviewer_note=payload.reviewer_note; row.included_in_report=payload.included_in_report and payload.review_state!="EXCLUDED"; db.commit()
    return {"id":row.id,"review_state":row.review_state,"reviewer_note":row.reviewer_note,"included_in_report":row.included_in_report}


@app.get("/api/v1/sessions/{session_id}/activities")
def activity_segments(session_id: int, db: DBSession = Depends(get_db)):
    if not db.get(models.Session,session_id): raise HTTPException(404,"Session not found")
    rows=db.scalars(select(models.ActivitySegment).where(models.ActivitySegment.session_id==session_id).order_by(models.ActivitySegment.start_seconds)).all()
    return [{"id":r.id,"activity_type":r.activity_type,"custom_label":r.custom_label,"start_seconds":r.start_seconds,"end_seconds":r.end_seconds,"confirmed":r.confirmed} for r in rows]


@app.post("/api/v1/sessions/{session_id}/activities")
def add_activity_segment(session_id: int, payload: schemas.ActivitySegmentCreate, db: DBSession = Depends(get_db)):
    session=db.get(models.Session,session_id)
    if not session: raise HTTPException(404,"Session not found")
    if payload.end_seconds is not None and payload.end_seconds<=payload.start_seconds: raise HTTPException(422,"end_seconds must be after start_seconds")
    active=db.scalar(select(models.ActivitySegment).where(models.ActivitySegment.session_id==session_id,models.ActivitySegment.end_seconds.is_(None)).order_by(desc(models.ActivitySegment.start_seconds)))
    if active and active.start_seconds<payload.start_seconds: active.end_seconds=payload.start_seconds
    row=models.ActivitySegment(session_id=session_id,**payload.model_dump()); session.activity_context=payload.activity_type; db.add(row); db.commit(); db.refresh(row)
    return {"id":row.id,"activity_type":row.activity_type,"start_seconds":row.start_seconds,"end_seconds":row.end_seconds,"confirmed":row.confirmed}


@app.get("/api/v1/sessions/{session_id}/quality")
def session_quality(session_id: int, db: DBSession = Depends(get_db)):
    if not db.get(models.Session, session_id): raise HTTPException(404, "Session not found")
    rows = db.scalars(select(models.QualityAssessment).where(models.QualityAssessment.session_id == session_id).order_by(models.QualityAssessment.timestamp)).all()
    if not rows: return {"session_id": session_id, "overall_quality": None, "status": "UNAVAILABLE", "warnings": ["No processed quality evidence is available."], "timeline": [], "frame_quality": frame_quality_metric(rows, None, [])}
    scores = [row.overall_quality for row in rows if row.overall_quality is not None]
    overall = round(sum(scores) / len(scores), 2) if scores else None
    warnings = sorted({warning for row in rows for warning in row.details.get("warnings", [])})
    status = "UNAVAILABLE" if overall is None else "GOOD" if overall >= 70 else "LIMITED" if overall >= 40 else "POOR"
    return {"session_id": session_id, "overall_quality": overall, "status": status, "warnings": warnings, "timeline": [{"timestamp": row.timestamp, **row.details} for row in rows], "frame_quality": frame_quality_metric(rows, overall, warnings)}


@app.get("/api/sessions/{session_id}/video")
def session_video(session_id: int, annotated: bool = True, db: DBSession = Depends(get_db)):
    row = db.get(models.Session, session_id)
    if not row: raise HTTPException(404, "Session not found")
    path = _managed_file(row.annotated_video_path if annotated else row.video_path)
    if path is None: raise HTTPException(404, "Requested video is not available")
    return FileResponse(path, filename=path.name, media_type="video/mp4" if path.suffix.lower() == ".mp4" else "video/x-msvideo")


@app.get("/api/sessions/{session_id}/timeline")
@app.get("/api/sessions/{session_id}/metrics")
def timeline(session_id: int, db: DBSession = Depends(get_db)):
    rows = db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id == session_id).order_by(models.AnalyticsSnapshot.timestamp)).all()
    return [{"timestamp": row.timestamp, "student_count": row.student_count, "current_occupancy_count": row.current_occupancy_count, "peak_occupancy_count": row.peak_occupancy_count, "occupancy_rate": row.occupancy_rate, "estimated_unique_tracks": row.estimated_unique_tracks, "verified_attendance_rate": None, "metrics": row.details.get("metrics", {}), "attention": row.attention_score, "engagement": row.engagement_score, "fatigue": row.fatigue_score, "drowsiness": row.drowsiness_count, "yawning": row.yawning_count, "raised_hands": row.raised_hands, "distracted_students": row.distracted_students, "looking_down": row.looking_down_students, "looking_away": row.looking_away_students, "occupied_seats": row.occupied_seats, "empty_seats": row.empty_seats, "occupancy": row.occupied_seats, "mode": row.details.get("mode", "REAL")} for row in rows]


@app.get("/api/sessions/{session_id}/report", dependencies=[Depends(rate_limit("report"))])
def report(session_id: int, format: str = "csv", db: DBSession = Depends(get_db)):
    session = db.get(models.Session, session_id)
    if not session: raise HTTPException(404, "Session not found")
    if session.status != "COMPLETED": raise HTTPException(409, "Report is unavailable until processing completes")
    if format not in {"csv", "pdf", "metrics"}: raise HTTPException(400, "Report format must be csv, pdf, or metrics")
    stored = db.scalar(select(models.Report).where(models.Report.session_id == session_id, models.Report.format == format))
    factory = {"pdf": create_pdf_report, "metrics": create_metrics_csv_report}.get(format, create_csv_report)
    path = _managed_file(stored.path) if stored else None
    if path is None:
        path = factory(db, session_id)
        upsert_report(db, session_id, format, path); db.commit()
    return FileResponse(path, filename=path.name, media_type="application/pdf" if format == "pdf" else "text/csv")


@app.get("/api/dashboard/summary")
@app.get("/api/dashboard")
def dashboard_summary(db: DBSession = Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    sessions=_accessible_sessions(db,user);ids=[row.id for row in sessions];latest=db.scalar(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id.in_(ids)).order_by(desc(models.AnalyticsSnapshot.id))) if ids else None
    latest_session=max(sessions,key=lambda row:row.id,default=None);recent_events=db.scalars(select(models.Event).where(models.Event.session_id.in_(ids)).order_by(desc(models.Event.id)).limit(8)).all() if ids else []
    return {"sessions": len(sessions), "active_sessions": sum(row.status in {"INITIALIZING", "PROCESSING", "FINALIZING"} for row in sessions), "latest": None if not latest else {"students": latest.student_count, "occupancy_rate": latest.occupancy_rate, "verified_attendance_rate": None, "metrics": latest.details.get("metrics", {}), "attention": latest.attention_score, "engagement": latest.engagement_score, "fatigue": latest.fatigue_score, "drowsiness": latest.drowsiness_count, "yawning": latest.yawning_count, "raised_hands": latest.raised_hands, "empty_seats": latest.empty_seats, "occupancy": latest.occupied_seats}, "demo_mode": settings.demo_mode, "analytics_mode": latest_session.analytics_mode if latest_session else ("DEMO" if settings.demo_mode else "REAL"), "current_session": None if not latest_session else {"id": latest_session.id, "name": latest_session.name, "status": latest_session.status, "stage": latest_session.processing_stage}, "last_updated": None if not latest else latest.timestamp, "recent_events": [{"session_id": row.session_id, "timestamp": row.timestamp, "type": row.event_type, "severity": row.severity, "message": row.message} for row in recent_events]}


@app.get("/api/dashboard/trends")
def dashboard_trends(db: DBSession = Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    ids=[row.id for row in _accessible_sessions(db,user)];rows=db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id.in_(ids)).order_by(desc(models.AnalyticsSnapshot.id)).limit(60)).all() if ids else []
    return [{"timestamp": row.timestamp, "engagement": row.engagement_score, "attention": row.attention_score, "fatigue": row.fatigue_score, "student_count": row.student_count, "raised_hands": row.raised_hands, "drowsiness": row.drowsiness_count, "occupancy": row.occupied_seats} for row in reversed(rows)]


_QUALITY_TIER_THRESHOLDS = {"HIGH": 0.8, "MODERATE": 0.5, "LOW": 0.0}

@app.get("/api/v1/dashboard/overview")
def dashboard_overview(classroom_id:int|None=None,course_id:int|None=None,start_date:datetime|None=None,end_date:datetime|None=None,data_source:str="REAL",db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    """Bounded dashboard summary: session status counts, recent sessions/
    reports, a data-quality breakdown, and report/classroom counts - each
    computed with at most a handful of queries regardless of how many
    sessions exist, never one query per session."""
    if start_date and end_date and start_date>end_date:raise _structured_error(400,"INVALID_DATE_RANGE","start_date must not be after end_date.")
    if data_source.upper() not in {"REAL","DEMO","TEST","ALL"}:raise _structured_error(400,"INVALID_DATA_SOURCE","data_source must be REAL, DEMO, TEST, or ALL.")
    statement=select(models.Session).where(models.Session.archived.is_(False))
    if classroom_id:statement=statement.where(models.Session.classroom_id==classroom_id)
    if course_id:statement=statement.where(models.Session.course_id==course_id)
    if start_date:statement=statement.where(models.Session.created_at>=start_date)
    if end_date:statement=statement.where(models.Session.created_at<=end_date)
    source=data_source.upper()
    if source=="REAL":statement=statement.where(models.Session.analytics_mode=="REAL",models.Session.is_test.is_(False))
    elif source=="DEMO":statement=statement.where(models.Session.analytics_mode=="DEMO",models.Session.is_test.is_(False))
    elif source=="TEST":statement=statement.where(models.Session.is_test.is_(True))
    sessions=_accessible_sessions(db,user,statement.order_by(desc(models.Session.created_at)))
    ids=[s.id for s in sessions]
    status_counts=Counter(s.status for s in sessions)

    # One grouped query for per-session snapshot coverage (never one query
    # per session): fraction of snapshots with any detected student.
    coverage_by_session:dict[int,float]={}
    if ids:
        rows=db.execute(select(models.AnalyticsSnapshot.session_id,func.count(),func.sum(case((models.AnalyticsSnapshot.student_count>0,1),else_=0))).where(models.AnalyticsSnapshot.session_id.in_(ids)).group_by(models.AnalyticsSnapshot.session_id)).all()
        for session_id,total,present in rows:
            if total:coverage_by_session[session_id]=round((present or 0)/total,3)
    coverages=list(coverage_by_session.values())
    average_coverage=round(sum(coverages)/len(coverages),3) if coverages else None

    quality_tiers={"HIGH":0,"MODERATE":0,"LOW":0,"INSUFFICIENT_EVIDENCE":0}
    for session in sessions:
        coverage=coverage_by_session.get(session.id)
        if coverage is None:quality_tiers["INSUFFICIENT_EVIDENCE"]+=1
        elif coverage>=_QUALITY_TIER_THRESHOLDS["HIGH"]:quality_tiers["HIGH"]+=1
        elif coverage>=_QUALITY_TIER_THRESHOLDS["MODERATE"]:quality_tiers["MODERATE"]+=1
        else:quality_tiers["LOW"]+=1

    reports_count=db.scalar(select(func.count(func.distinct(models.Report.session_id))).where(models.Report.session_id.in_(ids))) if ids else 0
    classroom_statement=select(models.Classroom).where(models.Classroom.active.is_(True))
    if user.role!="ADMINISTRATOR":classroom_statement=classroom_statement.where(or_(models.Classroom.owner_user_id==user.id,models.Classroom.owner_user_id.is_(None)))
    classrooms_count=len(db.scalars(classroom_statement).all())

    recent_sessions=[{"id":s.id,"name":s.name,"classroom_id":s.classroom_id,"course_id":s.course_id,"activity_context":s.activity_context,"source_type":s.source_type,"status":s.status,"created_at":s.created_at,"duration":s.duration,"coverage":coverage_by_session.get(s.id)} for s in sessions[:8]]
    recent_reports=db.scalars(select(models.Report).where(models.Report.session_id.in_(ids)).order_by(desc(models.Report.id)).limit(8)).all() if ids else []
    report_session_names={s.id:s.name for s in sessions}
    recent_events=db.scalars(select(models.Event).where(models.Event.session_id.in_(ids)).order_by(desc(models.Event.id)).limit(8)).all() if ids else []

    return {
        "data_source":source,"classroom_id":classroom_id,"course_id":course_id,
        "session_counts":{"total":len(sessions),**{k.lower():v for k,v in status_counts.items()}},
        "reports_available":reports_count,"classrooms_configured":classrooms_count,
        "average_valid_observation_coverage":average_coverage,
        "data_quality":{"tiers":quality_tiers,"thresholds":{"high_min_coverage":_QUALITY_TIER_THRESHOLDS["HIGH"],"moderate_min_coverage":_QUALITY_TIER_THRESHOLDS["MODERATE"],"definition":"Coverage is the fraction of processed frames with at least one detected person; sessions with zero processed frames are INSUFFICIENT_EVIDENCE."}},
        "recent_sessions":recent_sessions,
        "recent_reports":[{"session_id":r.session_id,"session_name":report_session_names.get(r.session_id,f"Session {r.session_id}"),"format":r.format,"created_at":r.created_at} for r in recent_reports],
        "recent_events":[{"session_id":e.session_id,"timestamp":e.timestamp,"event_type":e.event_type,"severity":e.severity,"review_state":e.review_state} for e in recent_events],
    }


@app.get("/api/seat-configurations")
def seat_configurations(classroom_id: int = 1, db: DBSession = Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    rows = db.scalars(select(models.SeatConfiguration).where(models.SeatConfiguration.classroom_id == classroom_id)).all()
    return [{"id": row.id, "classroom_id": row.classroom_id, "name": row.name, "regions": row.regions} for row in rows]


@app.get("/api/v1/classrooms")
def classrooms(q: str="", active: bool | None=None, page: int=1, page_size: int=50, db: DBSession = Depends(get_db), user: Principal=Depends(require("analytics:view"))):
    statement=select(models.Classroom)
    if user.role!="ADMINISTRATOR": statement=statement.where(or_(models.Classroom.owner_user_id==user.id,models.Classroom.owner_user_id.is_(None),models.Classroom.id.in_(select(models.Course.classroom_id).join(models.CourseMembership,models.CourseMembership.course_id==models.Course.id).where(models.CourseMembership.user_id==user.id))))
    if q: statement=statement.where(models.Classroom.name.ilike(f"%{q}%"))
    if active is not None: statement=statement.where(models.Classroom.active==active)
    rows=db.scalars(statement.order_by(models.Classroom.name).offset((max(page,1)-1)*min(page_size,100)).limit(min(page_size,100))).all()
    return [{"id":r.id,"name":r.name,"description":r.description,"location_label":r.location_label,"building":r.building,"room":r.room,"active":r.active,"capacity":r.total_seats,"expected_students":r.total_students,"reference_image_path":r.reference_image_path} for r in rows]


@app.get("/api/v1/classrooms/{classroom_id}/layouts")
def classroom_layouts(classroom_id: int, db: DBSession = Depends(get_db)):
    if not db.get(models.Classroom,classroom_id): raise HTTPException(404,"Classroom not found")
    rows=db.scalars(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id==classroom_id).order_by(desc(models.ClassroomLayout.version))).all()
    return [{"id":r.id,"classroom_id":r.classroom_id,"name":r.name,"version":r.version,"active":r.active,"reference_image_path":r.reference_image_path,"regions":[{"id":region.id,"region_key":region.region_key,"name":region.name,"region_type":region.region_type,"polygon":region.polygon,"active":region.active} for region in r.regions]} for r in rows]


@app.post("/api/v1/classrooms/{classroom_id}/reference-image")
async def upload_reference_image(classroom_id: int, file: UploadFile = File(...), layout_id: int | None = None, db: DBSession = Depends(get_db)):
    classroom=db.get(models.Classroom,classroom_id)
    if not classroom: raise HTTPException(404,"Classroom not found")
    suffix=Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg",".jpeg",".png",".webp"}: raise HTTPException(415,"Supported reference images: JPG, PNG, WEBP")
    content=await file.read(settings.max_reference_image_mb*1024*1024+1)
    if len(content)>settings.max_reference_image_mb*1024*1024: raise HTTPException(413,f"Reference image exceeds {settings.max_reference_image_mb} MB")
    image=cv2.imdecode(np.frombuffer(content,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.shape[0]<32 or image.shape[1]<32: raise HTTPException(422,"Reference image is invalid or too small")
    path=settings.classroom_reference_dir/f"classroom_{classroom_id}_{uuid.uuid4().hex}{suffix}"; path.write_bytes(content); classroom.reference_image_path=str(path)
    if layout_id is not None:
        layout=db.get(models.ClassroomLayout,layout_id)
        if not layout or layout.classroom_id!=classroom_id: path.unlink(missing_ok=True); raise HTTPException(404,"Layout not found")
        layout.reference_image_path=str(path)
    db.commit(); return {"classroom_id":classroom_id,"layout_id":layout_id,"status":"AVAILABLE","url":f"/api/v1/classrooms/{classroom_id}/reference-image"}


@app.post("/api/v1/classrooms/{classroom_id}/reference-image/capture")
def capture_reference_image(classroom_id: int, session_id: int, timestamp: float = 0, layout_id: int | None = None, db: DBSession = Depends(get_db)):
    classroom=db.get(models.Classroom,classroom_id); session=db.get(models.Session,session_id)
    if not classroom: raise HTTPException(404,"Classroom not found")
    if not session or not session.video_path or not Path(session.video_path).exists(): raise HTTPException(404,"Session source video is unavailable")
    capture=cv2.VideoCapture(session.video_path); capture.set(cv2.CAP_PROP_POS_MSEC,max(0,timestamp)*1000); ok,frame=capture.read(); capture.release()
    if not ok: raise HTTPException(422,"A reference frame could not be decoded at that timestamp")
    path=settings.classroom_reference_dir/f"classroom_{classroom_id}_{uuid.uuid4().hex}.jpg"; written=cv2.imwrite(str(path),frame)
    if not written: raise HTTPException(500,"Reference frame could not be saved")
    classroom.reference_image_path=str(path)
    if layout_id is not None:
        layout=db.get(models.ClassroomLayout,layout_id)
        if not layout or layout.classroom_id!=classroom_id: path.unlink(missing_ok=True); raise HTTPException(404,"Layout not found")
        layout.reference_image_path=str(path)
    db.commit(); return {"classroom_id":classroom_id,"layout_id":layout_id,"status":"AVAILABLE","url":f"/api/v1/classrooms/{classroom_id}/reference-image"}


@app.get("/api/v1/classrooms/{classroom_id}/reference-image")
def classroom_reference_image(classroom_id: int, db: DBSession = Depends(get_db)):
    classroom=db.get(models.Classroom,classroom_id)
    if not classroom or not classroom.reference_image_path or not Path(classroom.reference_image_path).exists(): raise HTTPException(404,"Reference image is unavailable")
    path=Path(classroom.reference_image_path); return FileResponse(path,media_type={".png":"image/png",".webp":"image/webp"}.get(path.suffix.lower(),"image/jpeg"))


@app.post("/api/v1/classrooms/{classroom_id}/layouts")
def create_classroom_layout(classroom_id: int, payload: schemas.ClassroomLayoutCreate, db: DBSession = Depends(get_db), user: Principal = Depends(require("layout:manage"))):
    classroom=db.get(models.Classroom,classroom_id)
    if not classroom: raise HTTPException(404,"Classroom not found")
    check=validate_layout(payload.regions)
    if not check["valid"]: raise _structured_error(422,"INVALID_LAYOUT","The layout contains invalid regions; nothing was saved.",check["errors"])
    version=(db.scalar(select(func.max(models.ClassroomLayout.version)).where(models.ClassroomLayout.classroom_id==classroom_id)) or 0)+1
    for prior in db.scalars(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id==classroom_id,models.ClassroomLayout.active.is_(True))).all(): prior.active=False
    row=models.ClassroomLayout(classroom_id=classroom_id,name=payload.name,version=version,active=True,reference_image_path=payload.reference_image_path or classroom.reference_image_path)
    row.regions=[models.ClassroomRegion(region_key=r.region_key,name=r.name,region_type=r.region_type,polygon=[p.model_dump() for p in r.polygon],active=r.active) for r in payload.regions]
    db.add(row); db.commit(); db.refresh(row)
    _audit(db,user,"LAYOUT_CREATED","LAYOUT",row.id,{"classroom_id":classroom_id,"version":row.version,"regions":len(row.regions)});db.commit()
    return {"id":row.id,"classroom_id":classroom_id,"name":row.name,"version":row.version,"active":row.active,"warnings":check["warnings"],"regions":[{"id":r.id,"region_key":r.region_key,"name":r.name,"region_type":r.region_type,"polygon":r.polygon,"active":r.active} for r in row.regions]}


@app.post("/api/v1/layouts/validate")
def validate_layout_endpoint(payload: schemas.ClassroomLayoutCreate):
    """Dry-run geometry validation (self-intersection, degenerate/out-of-bounds polygons, overlaps). Saves nothing."""
    return validate_layout(payload.regions)


@app.delete("/api/v1/classrooms/{classroom_id}/layouts/{layout_id}")
def deactivate_layout(classroom_id: int, layout_id: int, db: DBSession = Depends(get_db)):
    row=db.get(models.ClassroomLayout,layout_id)
    if not row or row.classroom_id!=classroom_id: raise HTTPException(404,"Layout not found")
    row.active=False; db.commit(); return {"id":layout_id,"active":False}


@app.get("/api/v1/sessions/{session_id}/regions")
def session_regions(session_id: int, db: DBSession = Depends(get_db)):
    session=db.get(models.Session,session_id)
    if not session: raise HTTPException(404,"Session not found")
    layout=db.scalar(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id==session.classroom_id,models.ClassroomLayout.active.is_(True)).order_by(desc(models.ClassroomLayout.version))) if session.classroom_id else None
    if not layout: return {"session_id":session_id,"status":"UNCALIBRATED","label":"Estimated unoccupied capacity","regions":[]}
    observations=db.scalars(select(models.StudentObservation).where(models.StudentObservation.session_id==session_id)).all()
    return {"session_id":session_id,"status":"CALIBRATED","layout_id":layout.id,"layout_version":layout.version,"regions":region_summary(observations,layout.regions)}


@app.get("/api/v1/sessions/{session_id}/regions/preview")
def region_preview(session_id: int, db: DBSession = Depends(get_db)):
    session=db.get(models.Session,session_id)
    if not session: raise HTTPException(404,"Session not found")
    layout=db.scalar(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id==session.classroom_id,models.ClassroomLayout.active.is_(True)).order_by(desc(models.ClassroomLayout.version))) if session.classroom_id else None
    if not layout: return {"session_id":session_id,"status":"UNAVAILABLE","limitations":["No calibrated classroom layout is assigned."],"tracks":[]}
    latest=db.scalar(select(func.max(models.StudentObservation.timestamp)).where(models.StudentObservation.session_id==session_id))
    if latest is None: return {"session_id":session_id,"status":"INSUFFICIENT_EVIDENCE","limitations":["No anonymous track observations are available."],"tracks":[]}
    rows=db.scalars(select(models.StudentObservation).where(models.StudentObservation.session_id==session_id,models.StudentObservation.timestamp==latest)).all(); types={r.region_key:r.region_type for r in layout.regions}
    tracks=[{"anonymous_track":r.tracking_id,"bbox":r.bbox,"region_id":r.region_id,"assignment":"EXCLUDED" if types.get(r.region_id)=="EXCLUDED" else "MATCHED" if r.region_id else "UNMATCHED","confidence":r.confidence} for r in rows]
    return {"session_id":session_id,"timestamp":latest,"status":"AVAILABLE" if tracks else "INSUFFICIENT_EVIDENCE","preview_only":True,"identity":"anonymous","tracks":tracks,"limitations":[] if tracks else ["No tracks were visible in the latest processed sample."]}


@app.post("/api/v1/sessions/{session_id}/regions/heatmap")
def region_heatmap(session_id: int, payload: schemas.HeatMapRequest, db: DBSession = Depends(get_db)):
    session=db.get(models.Session,session_id)
    if not session: raise HTTPException(404,"Session not found")
    layout=db.scalar(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id==session.classroom_id,models.ClassroomLayout.active.is_(True)).order_by(desc(models.ClassroomLayout.version))) if session.classroom_id else None
    if not layout: return {"session_id":session_id,"metric":payload.metric,"status":"UNAVAILABLE","limitations":["No calibrated classroom layout is assigned."],"cells":[]}
    statement=select(models.StudentObservation).where(models.StudentObservation.session_id==session_id)
    if payload.start_seconds is not None: statement=statement.where(models.StudentObservation.timestamp>=payload.start_seconds)
    if payload.end_seconds is not None: statement=statement.where(models.StudentObservation.timestamp<=payload.end_seconds)
    regions=[r for r in layout.regions if not payload.region_ids or r.region_key in payload.region_ids]
    result=aggregate_region_heatmap(db.scalars(statement).all(),regions,payload.metric,payload.aggregation_interval)
    comparison=None
    if payload.compare_session_id is not None:
        other=db.get(models.Session,payload.compare_session_id)
        if not other: raise HTTPException(404,"Comparison session not found")
        if other.classroom_id!=session.classroom_id:
            comparison={"status":"UNAVAILABLE","limitations":["Sessions use different classroom calibrations."]}
        else:
            other_statement=select(models.StudentObservation).where(models.StudentObservation.session_id==other.id)
            if payload.start_seconds is not None: other_statement=other_statement.where(models.StudentObservation.timestamp>=payload.start_seconds)
            if payload.end_seconds is not None: other_statement=other_statement.where(models.StudentObservation.timestamp<=payload.end_seconds)
            comparison={"session_id":other.id,**aggregate_region_heatmap(db.scalars(other_statement).all(),regions,payload.metric,payload.aggregation_interval)}
    return {"session_id":session_id,"start_seconds":payload.start_seconds,"end_seconds":payload.end_seconds,"aggregation_interval":payload.aggregation_interval,"comparison":comparison,**result}


@app.post("/api/seat-configurations")
def save_seat_configuration(payload: schemas.SeatConfigurationCreate, db: DBSession = Depends(get_db),user:Principal=Depends(require("layout:manage"))):
    if not can_access_session(db,user,models.Session(classroom_id=payload.classroom_id)):raise HTTPException(403,"Classroom access denied")
    row = models.SeatConfiguration(classroom_id=payload.classroom_id, name=payload.name, regions=[region.model_dump() for region in payload.regions])
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "classroom_id": row.classroom_id, "name": row.name, "regions": row.regions}


@app.get("/api/classroom/occupancy")
def occupancy(db: DBSession = Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    ids=[row.id for row in _accessible_sessions(db,user)];latest=db.scalar(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id.in_(ids)).order_by(desc(models.AnalyticsSnapshot.id))) if ids else None
    return {"room_capacity": settings.total_seats, "current_occupancy_count": latest.current_occupancy_count if latest else 0, "peak_occupancy_count": latest.peak_occupancy_count if latest else 0, "estimated_unique_tracks": latest.estimated_unique_tracks if latest else 0, "verified_attendance_rate": None, "occupancy_rate": latest.occupancy_rate if latest else 0}


@app.get("/api/classroom/engagement")
def engagement(db: DBSession = Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    ids=[row.id for row in _accessible_sessions(db,user)];latest=db.scalar(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id.in_(ids)).order_by(desc(models.AnalyticsSnapshot.id))) if ids else None
    score = latest.engagement_score if latest else 0
    return {"estimated_engagement_index": score, "level": "LOW" if score < 40 else "MEDIUM" if score < 70 else "HIGH"}


@app.post("/api/search", dependencies=[Depends(rate_limit("search"))])
@app.post("/api/v1/search", dependencies=[Depends(rate_limit("search"))])
def search(payload: schemas.SearchRequest, db: DBSession = Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    if any(token in payload.query.lower() for token in (";", "--", " drop ", " delete ", " update ", " insert ", " alter ")):
        raise HTTPException(400,"Only read-only allowlisted analytics questions are accepted")
    source=payload.data_source.upper()
    def allowed(session: models.Session) -> bool:
        # RBAC is enforced first and always, regardless of data-source
        # filtering: semantic relevance must never substitute for authorization.
        if not can_access_session(db,user,session):return False
        if source=="ALL":return True
        if source=="REAL":return session.analytics_mode=="REAL" and not session.is_test
        if source=="DEMO":return session.analytics_mode=="DEMO" and not session.is_test
        return bool(session.is_test)  # TEST
    result=search_analytics(db,payload.query);result["data_source"]=source
    # Authorization and data-source separation are applied to every match after the semantic/keyword step, so relevance can never widen access.
    found=len(result.get("matches",[]));result["matches"]=[match for match in result.get("matches",[]) if (target:=db.get(models.Session,match.get("session_id"))) and allowed(target)]
    result.setdefault("applied_filters",[]).extend([{"name":"data_source","description":f"Data source is {source}"},{"name":"access","description":"Only sessions you are authorized to view"}])
    result["bounded"]={"limit":100,"returned":len(result["matches"]),"truncated":found>=100}
    return result


def _require_session(db, session_id):
    if not db.get(models.Session, session_id): raise HTTPException(404, "Session not found")


@app.get("/api/v1/sessions/{session_id}/audio")
def audio_analysis(session_id: int, db: DBSession = Depends(get_db)):
    _require_session(db,session_id); row=db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id==session_id))
    if not row: return {"session_id":session_id,"status":"NOT_PROCESSED","quality_status":"UNAVAILABLE","quality":{},"coverage":{},"limitations":["Audio intelligence has not run for this session."]}
    diarization="MODEL_DISABLED" if settings.diarization_provider=="NONE" else "MODEL_UNAVAILABLE"
    return {"session_id":session_id,"status":row.status,"quality_status":row.quality_status,"quality":row.quality,"coverage":row.coverage,"provider":row.provider,"model_version":row.model_version,"diarization_status":diarization,"diarization_provider":settings.diarization_provider,"limitations":row.limitations}


@app.get("/api/v1/sessions/{session_id}/transcript")
def transcript(session_id: int, db: DBSession = Depends(get_db)):
    _require_session(db,session_id); rows=db.scalars(select(models.TranscriptSegment).where(models.TranscriptSegment.session_id==session_id).order_by(models.TranscriptSegment.start_seconds)).all(); audio=db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id==session_id))
    status="AVAILABLE" if rows else "RETENTION_DELETED" if audio and audio.status=="RETENTION_DELETED" else "UNAVAILABLE"
    return {"session_id":session_id,"status":status,"identity":"anonymous","segments":[{"id":r.id,"start_seconds":r.start_seconds,"end_seconds":r.end_seconds,"text":r.corrected_text or r.original_text,"original_text":r.original_text,"corrected":r.corrected_text is not None,"confidence":r.confidence,"language":r.language,"speaker_role":r.speaker_role,"provider":r.provider,"model_version":r.model_version} for r in rows],"limitations":[] if rows else ["Transcript was removed by retention policy." if status=="RETENTION_DELETED" else "No transcript is available; no text was fabricated."]}


@app.put("/api/v1/transcript-segments/{segment_id}")
def correct_transcript(segment_id: str, payload: schemas.TranscriptCorrectionUpdate, db: DBSession = Depends(get_db)):
    row=db.get(models.TranscriptSegment,segment_id)
    if not row: raise HTTPException(404,"Transcript segment not found")
    previous=row.corrected_text or row.original_text; row.corrected_text=payload.corrected_text
    db.add(models.TranscriptCorrection(segment_id=row.id,previous_text=previous,corrected_text=payload.corrected_text)); db.commit()
    return {"id":row.id,"text":row.corrected_text,"corrected":True}


@app.get("/api/v1/transcript-segments/{segment_id}/corrections")
def correction_history(segment_id: str, db: DBSession = Depends(get_db)):
    if not db.get(models.TranscriptSegment,segment_id): raise HTTPException(404,"Transcript segment not found")
    rows=db.scalars(select(models.TranscriptCorrection).where(models.TranscriptCorrection.segment_id==segment_id).order_by(models.TranscriptCorrection.created_at)).all()
    return [{"id":r.id,"previous_text":r.previous_text,"corrected_text":r.corrected_text,"created_at":r.created_at} for r in rows]


@app.put("/api/v1/transcript-segments/{segment_id}/speaker-role")
def update_speaker_role(segment_id: str, payload: schemas.SpeakerRoleUpdate, db: DBSession = Depends(get_db)):
    row=db.get(models.TranscriptSegment,segment_id)
    if not row: raise HTTPException(404,"Transcript segment not found")
    row.speaker_role=payload.role; row.metadata_json={**row.metadata_json,"role_source":"MANUAL","anonymous":True}; db.commit()
    return {"id":row.id,"speaker_role":row.speaker_role,"identity":"anonymous","cross_session_matching":False}


@app.get("/api/v1/sessions/{session_id}/transcript/export")
def transcript_export(session_id: int, format: str="json", db: DBSession = Depends(get_db)):
    _require_session(db,session_id)
    try: path=create_transcript_export(db,session_id,format)
    except ValueError as error: raise HTTPException(400,str(error)) from error
    if not path: raise HTTPException(404,"Transcript unavailable or removed by retention policy")
    media={"json":"application/json","csv":"text/csv","txt":"text/plain"}[format.lower()]
    return FileResponse(path,media_type=media,filename=path.name)


@app.post("/api/v1/retention/transcripts/run")
def run_transcript_retention(confirm: bool = False, db: DBSession = Depends(get_db)):
    """Explicit administrator action: removes raw audio and transcript evidence past the retention age (aggregates are kept)."""
    if not confirm: raise _structured_error(400,"CONFIRMATION_REQUIRED","Set confirm=true to remove expired transcript and audio evidence.")
    return cleanup_expired_transcripts(db,settings)


@app.get("/api/v1/sessions/{session_id}/discourse")
def discourse(session_id: int, db: DBSession = Depends(get_db)):
    _require_session(db,session_id); row=db.scalar(select(models.DiscourseAnalysis).where(models.DiscourseAnalysis.session_id==session_id))
    return {"session_id":session_id,"status":row.status if row else "NOT_PROCESSED","metrics":row.metrics if row else {},"limitations":row.limitations if row else ["Discourse analysis has not run."]}


@app.get("/api/v1/sessions/{session_id}/content")
def lecture_content(session_id: int, db: DBSession = Depends(get_db)):
    _require_session(db,session_id); chapters=db.scalars(select(models.LectureChapter).where(models.LectureChapter.session_id==session_id).order_by(models.LectureChapter.start_seconds)).all(); items=db.scalars(select(models.GeneratedContentItem).where(models.GeneratedContentItem.session_id==session_id).order_by(models.GeneratedContentItem.content_type,models.GeneratedContentItem.ordinal)).all()
    return {"session_id":session_id,"status":"AVAILABLE" if chapters or items else "UNAVAILABLE","generated_label":"AI/deterministically generated from transcript evidence","chapters":[{"id":r.id,"title":r.title,"start_seconds":r.start_seconds,"end_seconds":r.end_seconds,"confidence":r.confidence,"evidence_segment_ids":r.evidence_segment_ids} for r in chapters],"items":[{"id":r.id,"type":r.content_type,"text":r.edited_text or r.text,"original_text":r.text,"edited":r.edited_text is not None,"confidence":r.confidence,"evidence_segment_ids":r.evidence_segment_ids,"timestamps":r.timestamps,"provider":r.provider} for r in items],"limitations":[] if chapters or items else ["Transcript evidence is required; content was not generated."]}


@app.put("/api/v1/content-items/{item_id}")
def edit_content(item_id: int, payload: schemas.GeneratedContentUpdate, db: DBSession = Depends(get_db)):
    row=db.get(models.GeneratedContentItem,item_id)
    if not row: raise HTTPException(404,"Generated content item not found")
    row.edited_text=payload.edited_text; db.commit(); return {"id":row.id,"text":row.edited_text,"edited":True}


@app.get("/api/v1/sessions/{session_id}/evidence-graph")
def evidence_graph(session_id: int, db: DBSession = Depends(get_db)):
    _require_session(db,session_id); row=db.scalar(select(models.EvidenceFusionResult).where(models.EvidenceFusionResult.session_id==session_id).order_by(desc(models.EvidenceFusionResult.id)))
    if not row: return {"session_id":session_id,"status":"NOT_PROCESSED","nodes":[],"edges":[],"limitations":["Evidence fusion has not run."]}
    nodes=[{"id":c["name"],"type":"EVIDENCE","value":c["value"],"confidence":c["confidence"],"effective_weight":c["effective_weight"],"included":c.get("included",True),"exclusion_reason":c.get("exclusion_reason")} for c in row.components]; nodes.append({"id":"fusion","type":"FUSED_ESTIMATE","value":row.value,"confidence":row.confidence})
    return {"session_id":session_id,"status":row.status,"methodology_version":row.methodology_version,"context":row.coverage.get("context"),"value":row.value,"confidence":row.confidence,"coverage":row.coverage,"nodes":nodes,"edges":[{"source":c["name"],"target":"fusion","weight":c["effective_weight"]} for c in row.components if c.get("included",True)],"limitations":row.limitations,"disclaimer":"Explainable research estimate; not a medical, psychological, or pedagogical conclusion."}


@app.get("/api/reports")
def reports(db: DBSession = Depends(get_db),user:Principal=Depends(require("report:generate"))):
    rows=_accessible_sessions(db,user,select(models.Session).where(models.Session.status == "COMPLETED").order_by(desc(models.Session.created_at)))
    return [{**crud.session_summary(db, row.id), "name": row.name, "created_at": row.created_at, "analytics_mode": row.analytics_mode} for row in rows]


@app.get("/api/v1/reports", dependencies=[Depends(rate_limit("report"))])
def reports_v1(q:str|None=None,source_type:str|None=None,status:str|None=None,activity_context:str|None=None,format:str|None=None,start_date:datetime|None=None,end_date:datetime|None=None,course_id:int|None=None,classroom_id:int|None=None,data_source:str="REAL",page:int=1,page_size:int=20,db:DBSession=Depends(get_db),user:Principal=Depends(require("report:generate"))):
    if start_date and end_date and start_date>end_date: raise _structured_error(400,"INVALID_DATE_RANGE","start_date must not be after end_date.")
    page=max(1,page);page_size=max(1,min(100,page_size));statement=select(models.Session).where(models.Session.archived.is_(False))
    if q:statement=statement.where(or_(models.Session.name.ilike(f"%{q}%"),models.Session.source_filename.ilike(f"%{q}%")))
    if source_type:statement=statement.where(models.Session.source_type==source_type.upper())
    if status:statement=statement.where(models.Session.status==status.upper())
    if activity_context:statement=statement.where(models.Session.activity_context==activity_context.upper())
    if start_date:statement=statement.where(models.Session.created_at>=start_date)
    if end_date:statement=statement.where(models.Session.created_at<=end_date)
    if course_id:statement=statement.where(models.Session.course_id==course_id)
    if classroom_id:statement=statement.where(models.Session.classroom_id==classroom_id)
    if data_source.upper() not in {"REAL","DEMO","TEST","ALL"}:raise _structured_error(400,"INVALID_DATA_SOURCE","data_source must be REAL, DEMO, TEST, or ALL.")
    statement=_apply_data_source(statement,data_source)
    if format and format.lower() not in {"csv","pdf","metrics"}:raise _structured_error(400,"INVALID_FORMAT","format must be csv, pdf, or metrics.")
    accessible=bulk_accessible_sessions(db,user,db.scalars(statement.order_by(desc(models.Session.created_at))).all())
    if format:
        # A session's Report rows are cheap to check in bulk once, up front, so the
        # format filter never adds a query per candidate session.
        ids_with_format=set(db.scalars(select(models.Report.session_id).where(models.Report.format==format.lower())).all())
        accessible=[row for row in accessible if row.id in ids_with_format]
    total=len(accessible);selected=accessible[(page-1)*page_size:page*page_size]
    selected_ids=[row.id for row in selected]
    # One grouped query for every selected session's available report formats,
    # instead of one query per row (the previous implementation's N+1).
    formats_by_session:dict[int,set[str]]={}
    if selected_ids:
        for session_id,report_format in db.execute(select(models.Report.session_id,models.Report.format).where(models.Report.session_id.in_(selected_ids))).all():
            formats_by_session.setdefault(session_id,set()).add(report_format)
    items=[]
    summaries=crud.batch_session_summaries(db,selected)
    for row in selected:
        summary=summaries[row.id];formats=formats_by_session.get(row.id,set())
        items.append({**summary,"name":row.name,"source_filename":row.source_filename,"source_type":row.source_type,"status":row.status,"stage":row.processing_stage,"classroom_id":row.classroom_id,"course_id":row.course_id,"activity_context":row.activity_context,"duration":row.duration,"progress":row.progress,"created_at":row.created_at,"analytics_mode":row.analytics_mode,"is_test":row.is_test,"error":row.error,"failure_code":row.failure_code,"job_id":row.job_id,"available_formats":sorted(formats),"report_ready":row.status=="COMPLETED" and {"pdf","csv"}<=formats})
    return {"items":items,"page":page,"page_size":page_size,"total":total,"pages":max(1,(total+page_size-1)//page_size)}


@app.get("/api/reports/{session_id}")
def report_alias(session_id: int, format: str = "pdf", db: DBSession = Depends(get_db)):
    return report(session_id, format, db)


@app.get("/api/session-comparison")
def compare_sessions(ids: str, db: DBSession = Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    selected = [int(value) for value in ids.split(",") if value.strip().isdigit()]
    if len(selected) < 2: raise HTTPException(400, "Select at least two session IDs")
    rows=[db.get(models.Session,session_id) for session_id in selected]
    if any(not row for row in rows):raise HTTPException(404,"Session not found")
    if any(not can_access_session(db,user,row) for row in rows):raise HTTPException(403,"Session access denied")
    return [crud.session_summary(db, session_id) for session_id in selected]


def _audit(db,user,action,kind,resource_id,details=None): db.add(models.AuditEntry(actor_user_id=user.id,action=action,resource_type=kind,resource_id=resource_id,details=details or {}))
def _course_access(db,user,course):
    if user.role=="ADMINISTRATOR" or course.owner_user_id in {None,user.id}: return True
    return bool(db.scalar(select(models.CourseMembership.id).where(models.CourseMembership.course_id==course.id,models.CourseMembership.user_id==user.id)))

@app.post("/api/v1/users")
def create_user(payload:schemas.UserCreate,db:DBSession=Depends(get_db),user:Principal=Depends(require("user:manage"))):
    if db.scalar(select(models.User.id).where(models.User.email==payload.email.lower())):raise HTTPException(409,"Email already exists")
    values=payload.model_dump(exclude={"password","email"});row=models.User(**values,email=payload.email.lower(),password_hash=hash_password(payload.password));db.add(row);db.flush();_audit(db,user,"USER_CREATED","USER",row.id,{"role":row.role});db.commit();return {"id":row.id,"email":row.email,"display_name":row.display_name,"role":row.role,"active":row.active}

@app.get("/api/v1/users")
def list_users(response: HttpResponse, q: str = "", role: str | None = None, active: bool | None = None, page: int = 1, page_size: int = 50, db: DBSession = Depends(get_db), user: Principal = Depends(require("user:manage"))):
    """Searchable, paginated user list (administrators only). Total count is returned in X-Total-Count."""
    statement = select(models.User)
    if q: statement = statement.where(or_(models.User.email.ilike(f"%{q}%"), models.User.display_name.ilike(f"%{q}%")))
    if role: statement = statement.where(models.User.role == role.upper())
    if active is not None: statement = statement.where(models.User.active.is_(active))
    page, page_size = max(1, page), max(1, min(200, page_size))
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = db.scalars(statement.order_by(models.User.email).offset((page - 1) * page_size).limit(page_size)).all()
    return [{"id": r.id, "email": r.email, "display_name": r.display_name, "role": r.role, "active": r.active, "created_at": r.created_at} for r in rows]


@app.get("/api/v1/auth/permissions")
def role_permissions(user: Principal = Depends(principal)):
    """Human-readable explanation of what each role may do, plus the caller's own permissions."""
    from .auth import PERMISSIONS
    explanations = {
        "ADMINISTRATOR": "Full access: users, settings, retention, classrooms, courses, sessions and reports.",
        "INSTRUCTOR": "Upload and manage own sessions, classrooms, courses and layouts; review events; write notes; generate reports.",
        "REVIEWER": "View sessions and analytics, review events and transcripts, write notes and generate reports. Cannot upload or change classrooms.",
        "VIEWER": "Read-only access to permitted sessions, analytics and reports.",
    }
    return {"you": {"role": user.role, "permissions": sorted(PERMISSIONS.get(user.role, set()))}, "roles": [{"role": role, "summary": explanations[role], "permissions": sorted(PERMISSIONS[role])} for role in explanations], "auth_enabled": settings.auth_enabled}


@app.put("/api/v1/users/{user_id}")
def update_user(user_id:int,payload:schemas.UserUpdate,db:DBSession=Depends(get_db),actor:Principal=Depends(require("user:manage"))):
    row=db.get(models.User,user_id)
    if not row:raise HTTPException(404,"User not found")
    if row.role=="ADMINISTRATOR" and (payload.role!="ADMINISTRATOR" or not payload.active):
        remaining=db.scalar(select(func.count(models.User.id)).where(models.User.role=="ADMINISTRATOR",models.User.active.is_(True)))
        if remaining<=1:raise HTTPException(409,"Cannot deactivate or demote the final administrator")
    before={"role":row.role,"active":row.active};row.display_name=payload.display_name;row.role=payload.role;row.active=payload.active;row.token_version+=1;_audit(db,actor,"USER_PERMISSION_UPDATED","USER",row.id,{"before":before,"after":{"role":row.role,"active":row.active}});db.commit();return {"id":row.id,"role":row.role,"active":row.active}

@app.post("/api/v1/classrooms")
def create_classroom(payload:schemas.ClassroomCreate,db:DBSession=Depends(get_db),user:Principal=Depends(require("classroom:manage"))):
    row=models.Classroom(**payload.model_dump(),owner_user_id=user.id,active=True);db.add(row);db.flush();_audit(db,user,"CLASSROOM_CREATED","CLASSROOM",row.id);db.commit();return {"id":row.id,"name":row.name,"active":row.active}

@app.put("/api/v1/classrooms/{classroom_id}")
def update_classroom(classroom_id:int,payload:schemas.ClassroomCreate,db:DBSession=Depends(get_db),user:Principal=Depends(require("classroom:manage"))):
    row=db.get(models.Classroom,classroom_id)
    if not row:raise HTTPException(404,"Classroom not found")
    if user.role!="ADMINISTRATOR" and row.owner_user_id not in {None,user.id}:raise HTTPException(403,"Classroom access denied")
    for key,value in payload.model_dump().items():setattr(row,key,value)
    _audit(db,user,"CLASSROOM_UPDATED","CLASSROOM",row.id);db.commit();return {"id":row.id,"name":row.name,"active":row.active}

@app.post("/api/v1/classrooms/{classroom_id}/archive")
def archive_classroom(classroom_id:int,restore:bool=False,db:DBSession=Depends(get_db),user:Principal=Depends(require("classroom:manage"))):
    row=db.get(models.Classroom,classroom_id)
    if not row:raise HTTPException(404,"Classroom not found")
    if user.role!="ADMINISTRATOR" and row.owner_user_id not in {None,user.id}:raise HTTPException(403,"Classroom access denied")
    row.active=restore;_audit(db,user,"CLASSROOM_RESTORED" if restore else "CLASSROOM_ARCHIVED","CLASSROOM",row.id);db.commit();return {"id":row.id,"active":row.active}

@app.get("/api/v1/courses")
def courses(q:str="",active:bool|None=None,classroom_id:int|None=None,page:int=1,page_size:int=50,db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    statement=select(models.Course)
    if user.role!="ADMINISTRATOR":statement=statement.where(or_(models.Course.owner_user_id==user.id,models.Course.owner_user_id.is_(None),models.Course.id.in_(select(models.CourseMembership.course_id).where(models.CourseMembership.user_id==user.id))))
    if q:statement=statement.where(or_(models.Course.name.ilike(f"%{q}%"),models.Course.code.ilike(f"%{q}%")))
    if active is not None:statement=statement.where(models.Course.active==active)
    if classroom_id:statement=statement.where(models.Course.classroom_id==classroom_id)
    rows=db.scalars(statement.order_by(models.Course.code).offset((max(page,1)-1)*min(page_size,100)).limit(min(page_size,100))).all();return [{"id":r.id,"code":r.code,"name":r.name,"description":r.description,"academic_term":r.academic_term,"classroom_id":r.classroom_id,"active":r.active} for r in rows]

@app.post("/api/v1/courses")
def create_course(payload:schemas.CourseCreate,db:DBSession=Depends(get_db),user:Principal=Depends(require("course:manage"))):
    if payload.classroom_id and not db.get(models.Classroom,payload.classroom_id):raise HTTPException(404,"Classroom not found")
    row=models.Course(**payload.model_dump(),owner_user_id=user.id);db.add(row);db.flush();_audit(db,user,"COURSE_CREATED","COURSE",row.id);db.commit();return {"id":row.id,"code":row.code,"name":row.name,"active":row.active}

@app.put("/api/v1/courses/{course_id}")
def update_course(course_id:int,payload:schemas.CourseUpdate,db:DBSession=Depends(get_db),user:Principal=Depends(require("course:manage"))):
    row=db.get(models.Course,course_id)
    if not row:raise HTTPException(404,"Course not found")
    if not _course_access(db,user,row):raise HTTPException(403,"Course access denied")
    for key,value in payload.model_dump().items():setattr(row,key,value)
    _audit(db,user,"COURSE_UPDATED","COURSE",row.id);db.commit();return {"id":row.id,"active":row.active}

@app.post("/api/v1/courses/{course_id}/sessions")
def assign_course_session(course_id:int,payload:schemas.CourseSessionAssign,db:DBSession=Depends(get_db),user:Principal=Depends(require("course:manage"))):
    course=db.get(models.Course,course_id);session=db.get(models.Session,payload.session_id)
    if not course or not session:raise HTTPException(404,"Course or session not found")
    if not _course_access(db,user,course):raise HTTPException(403,"Course access denied")
    if course.classroom_id and session.classroom_id and course.classroom_id!=session.classroom_id:raise HTTPException(409,"Session classroom differs from course classroom")
    session.course_id=course.id;_audit(db,user,"SESSION_ASSIGNED","COURSE",course.id,{"session_id":session.id});db.commit();return {"course_id":course.id,"session_id":session.id}

@app.get("/api/v1/courses/{course_id}/sessions")
def course_sessions(course_id:int,db:DBSession=Depends(get_db),user:Principal=Depends(require("session:view"))):
    course=db.get(models.Course,course_id)
    if not course:raise HTTPException(404,"Course not found")
    if not _course_access(db,user,course):raise HTTPException(403,"Course access denied")
    rows=db.scalars(select(models.Session).where(models.Session.course_id==course_id).order_by(models.Session.created_at)).all();return [{"id":r.id,"name":r.name,"status":r.status,"context":r.activity_context,"created_at":r.created_at} for r in rows]

@app.get("/api/v1/courses/{course_id}/members")
def course_members(course_id:int,db:DBSession=Depends(get_db),user:Principal=Depends(require("course:manage"))):
    course=db.get(models.Course,course_id)
    if not course:raise HTTPException(404,"Course not found")
    if not _course_access(db,user,course):raise HTTPException(403,"Course access denied")
    rows=db.execute(select(models.CourseMembership,models.User).join(models.User,models.User.id==models.CourseMembership.user_id).where(models.CourseMembership.course_id==course_id)).all();return [{"user_id":member.user_id,"email":account.email,"display_name":account.display_name,"membership_role":member.membership_role,"active":account.active} for member,account in rows]

@app.post("/api/v1/courses/{course_id}/members")
def upsert_course_member(course_id:int,payload:schemas.CourseMembershipUpsert,db:DBSession=Depends(get_db),user:Principal=Depends(require("course:manage"))):
    course=db.get(models.Course,course_id);account=db.get(models.User,payload.user_id)
    if not course or not account:raise HTTPException(404,"Course or user not found")
    if not _course_access(db,user,course):raise HTTPException(403,"Course access denied")
    row=db.scalar(select(models.CourseMembership).where(models.CourseMembership.course_id==course_id,models.CourseMembership.user_id==payload.user_id))
    if row:row.membership_role=payload.membership_role
    else:row=models.CourseMembership(course_id=course_id,user_id=payload.user_id,membership_role=payload.membership_role);db.add(row)
    _audit(db,user,"COURSE_MEMBERSHIP_UPSERTED","COURSE",course_id,{"user_id":payload.user_id,"membership_role":payload.membership_role});db.commit();return {"course_id":course_id,"user_id":payload.user_id,"membership_role":payload.membership_role}

@app.delete("/api/v1/courses/{course_id}/members/{member_user_id}")
def remove_course_member(course_id:int,member_user_id:int,db:DBSession=Depends(get_db),user:Principal=Depends(require("course:manage"))):
    course=db.get(models.Course,course_id)
    if not course:raise HTTPException(404,"Course not found")
    if not _course_access(db,user,course):raise HTTPException(403,"Course access denied")
    row=db.scalar(select(models.CourseMembership).where(models.CourseMembership.course_id==course_id,models.CourseMembership.user_id==member_user_id))
    if not row:raise HTTPException(404,"Membership not found")
    db.delete(row);_audit(db,user,"COURSE_MEMBERSHIP_REMOVED","COURSE",course_id,{"user_id":member_user_id});db.commit();return {"course_id":course_id,"user_id":member_user_id,"removed":True}

@app.get("/api/v1/classrooms/{classroom_id}/dashboard")
def classroom_dashboard(classroom_id:int,db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    room=db.get(models.Classroom,classroom_id)
    if not room:raise HTTPException(404,"Classroom not found")
    if not can_access_session(db,user,models.Session(classroom_id=classroom_id)):raise HTTPException(403,"Classroom access denied")
    return {"classroom_id":classroom_id,**aggregate_dashboard(db,db.scalars(select(models.Session).where(models.Session.classroom_id==classroom_id)).all())}

@app.get("/api/v1/courses/{course_id}/dashboard")
def course_dashboard(course_id:int,db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    course=db.get(models.Course,course_id)
    if not course:raise HTTPException(404,"Course not found")
    if not _course_access(db,user,course):raise HTTPException(403,"Course access denied")
    return {"course_id":course_id,**aggregate_dashboard(db,db.scalars(select(models.Session).where(models.Session.course_id==course_id)).all())}

COMPARABLE_METRICS={"observable_participation","visual_orientation","possible_fatigue","occupancy","peak_occupancy","unoccupied_capacity","prolonged_eye_closure","yawning","raised_hands","frame_quality","camera_quality","audio_quality","question_count","fusion"}

def _resolve_comparison_sessions(db,user,session_ids:list[int]):
    if len(session_ids)!=len(set(session_ids)):raise _structured_error(400,"DUPLICATE_SESSION_IDS","Select each session only once.")
    if len(session_ids)<2:raise _structured_error(400,"TOO_FEW_SESSIONS","Select at least two sessions to compare.")
    if len(session_ids)>5:raise _structured_error(400,"TOO_MANY_SESSIONS","Select at most five sessions to compare.")
    found={row.id:row for row in db.scalars(select(models.Session).where(models.Session.id.in_(session_ids))).all()}
    missing=[sid for sid in session_ids if sid not in found]
    if missing:raise _structured_error(404,"SESSION_NOT_FOUND",f"Session(s) not found: {', '.join(str(i) for i in missing)}.")
    rows=[found[sid] for sid in session_ids]
    denied=[row.id for row in rows if not can_access_session(db,user,row)]
    if denied:raise _structured_error(403,"SESSION_ACCESS_DENIED",f"Access denied for session(s): {', '.join(str(i) for i in denied)}.")
    return rows

@app.post("/api/v1/analytics/compare", dependencies=[Depends(rate_limit("analytics"))])
def analytics_compare(payload:schemas.CompareRequest,db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    if not set(payload.metrics)<=COMPARABLE_METRICS:raise _structured_error(400,"INVALID_METRIC","Unsupported comparison metric.")
    rows=_resolve_comparison_sessions(db,user,payload.session_ids)
    return compare_evidence(db,rows,payload.metrics)

def _csv_safe(value):
    """Prevent CSV formula injection: a cell beginning with =, +, -, or @
    is prefixed with a leading apostrophe so spreadsheet software treats it
    as text, never as a formula, when the field came from user-controlled
    text (session/classroom/course names)."""
    text=str(value) if value is not None else ""
    return f"'{text}" if text[:1] in ("=","+","-","@") else text

@app.get("/api/v1/analytics/compare/export", dependencies=[Depends(rate_limit("analytics"))])
def analytics_compare_export(session_ids:str,metrics:str="",db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    try:parsed_ids=[int(v) for v in session_ids.split(",") if v.strip()]
    except ValueError:raise _structured_error(400,"INVALID_SESSION_IDS","session_ids must be a comma-separated list of integers.")
    if not parsed_ids:raise _structured_error(400,"INVALID_SESSION_IDS","session_ids must not be empty.")
    requested_metrics=[m for m in metrics.split(",") if m.strip()] or list(COMPARABLE_METRICS&set(CANONICAL_METRIC_NAMES)|{"frame_quality"})
    if not set(requested_metrics)<=COMPARABLE_METRICS:raise _structured_error(400,"INVALID_METRIC","Unsupported comparison metric.")
    rows=_resolve_comparison_sessions(db,user,parsed_ids)
    result=compare_evidence(db,rows,requested_metrics)
    session_lookup={s["session_id"]:s for s in result["sessions"]}
    classroom_names={c.id:c.name for c in db.scalars(select(models.Classroom)).all()}
    course_names={c.id:c.name for c in db.scalars(select(models.Course)).all()}
    fields=["session_id","session_name","classroom","course","activity_context","source_type","metric_name","value","available","reason","coverage","confidence","valid_observations","total_observations"]
    buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader()
    for metric_name in requested_metrics:
        if metric_name not in result["metric_results"]:continue
        for sid_str,contract in result["metric_results"][metric_name].items():
            session_row=session_lookup.get(int(sid_str),{})
            writer.writerow({
                "session_id":int(sid_str),
                "session_name":_csv_safe(session_row.get("name")),
                "classroom":_csv_safe(classroom_names.get(session_row.get("classroom_id"),"")),
                "course":_csv_safe(course_names.get(session_row.get("course_id"),"")),
                "activity_context":session_row.get("context"),
                "source_type":session_row.get("source_type"),
                "metric_name":metric_name,
                "value":"" if contract["value"] is None else contract["value"],
                "available":contract["available"],
                "reason":contract["reason"] or "",
                "coverage":"" if contract["coverage"] is None else contract["coverage"],
                "confidence":"" if contract["confidence"] is None else contract["confidence"],
                "valid_observations":contract["valid_observations"],
                "total_observations":contract["total_observations"],
            })
    filename=f"session_comparison_{'-'.join(str(i) for i in parsed_ids)}.csv"
    return Response(content=buffer.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="{filename}"'})

@app.get("/api/v1/analytics/trends", dependencies=[Depends(rate_limit("analytics"))])
def analytics_trends(course_id:int|None=None,classroom_id:int|None=None,period:str="session",metric:str="observable_participation",data_source:str="REAL",start_date:datetime|None=None,end_date:datetime|None=None,activity_context:str|None=None,confidence_min:float|None=None,minimum_coverage:float|None=None,include_archived:bool=False,rolling_window:int=3,db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    if minimum_coverage is not None and not (0.0<=minimum_coverage<=1.0):raise _structured_error(400,"INVALID_COVERAGE","minimum_coverage must be between 0.0 and 1.0.")
    if confidence_min is not None and not (0.0<=confidence_min<=1.0):raise _structured_error(400,"INVALID_CONFIDENCE","confidence_min must be between 0.0 and 1.0.")
    if period not in {"session","daily","weekly","monthly"}:raise _structured_error(400,"INVALID_PERIOD","Period must be session, daily, weekly, or monthly.")
    if start_date and end_date and start_date>end_date:raise _structured_error(400,"INVALID_DATE_RANGE","start_date must not be after end_date.")
    if rolling_window<2 or rolling_window>12:raise _structured_error(400,"INVALID_PERIOD","rolling_window must be between 2 and 12.")
    if metric not in COMPARABLE_METRICS:raise _structured_error(400,"INVALID_METRIC","Unsupported trend metric.")
    if data_source.upper() not in {"REAL","DEMO","TEST","ALL"}:raise _structured_error(400,"INVALID_DATA_SOURCE","data_source must be REAL, DEMO, TEST, or ALL.")
    statement=select(models.Session)
    if not include_archived:statement=statement.where(models.Session.archived.is_(False))
    if course_id:statement=statement.where(models.Session.course_id==course_id)
    if classroom_id:statement=statement.where(models.Session.classroom_id==classroom_id)
    if start_date:statement=statement.where(models.Session.created_at>=start_date)
    if end_date:statement=statement.where(models.Session.created_at<=end_date)
    if activity_context:statement=statement.where(models.Session.activity_context==activity_context)
    if data_source.upper()=="REAL":statement=statement.where(models.Session.analytics_mode=="REAL",models.Session.is_test.is_(False))
    elif data_source.upper()=="DEMO":statement=statement.where(models.Session.analytics_mode=="DEMO",models.Session.is_test.is_(False))
    elif data_source.upper()=="TEST":statement=statement.where(models.Session.is_test.is_(True))
    rows=bulk_accessible_sessions(db,user,db.scalars(statement.order_by(models.Session.created_at)).all());points=trend_buckets(db,rows,period,rolling_window,metric)
    total_points=len(points)
    if confidence_min is not None:points=[p for p in points if p["confidence"] is not None and p["confidence"]>=confidence_min]
    if minimum_coverage:points=[p for p in points if p["coverage"] is not None and p["coverage"]>=minimum_coverage]  # 0 means "no minimum": unavailable periods stay visible as gaps
    return {"period":period,"metric":metric,"data_source":data_source.upper(),"filters_applied":{"minimum_coverage":minimum_coverage,"confidence_min":confidence_min,"classroom_id":classroom_id,"course_id":course_id,"activity_context":activity_context,"start_date":start_date,"end_date":end_date},"excluded_by_filters":total_points-len(points),"timezone":"UTC","aggregation_rule":"Coverage-weighted mean of available evidence, grouped separately by activity context and methodology version. Null and insufficient evidence are never converted to zero.","points":points,"status":"AVAILABLE" if any(p["value"] is not None for p in points) else "INSUFFICIENT_EVIDENCE"}

@app.get("/api/v1/analytics/filter", dependencies=[Depends(rate_limit("analytics"))])
def analytics_filter(course_id:int|None=None,classroom_id:int|None=None,start_date:datetime|None=None,end_date:datetime|None=None,activity_context:str|None=None,processing_status:str|None=None,audio_status:str|None=None,camera_quality_max:float|None=None,confidence_min:float|None=None,include_archived:bool=False,page:int=1,page_size:int=50,db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    if start_date and end_date and start_date>end_date:raise HTTPException(400,"start_date must not be after end_date")
    statement=select(models.Session)
    if course_id:statement=statement.where(models.Session.course_id==course_id)
    if classroom_id:statement=statement.where(models.Session.classroom_id==classroom_id)
    if start_date:statement=statement.where(models.Session.created_at>=start_date)
    if end_date:statement=statement.where(models.Session.created_at<=end_date)
    if activity_context:statement=statement.where(models.Session.activity_context==activity_context)
    if processing_status:statement=statement.where(models.Session.status==processing_status)
    if not include_archived:statement=statement.where(models.Session.archived.is_(False))
    evidence=[]
    for item in evidence_for_sessions(db,bulk_accessible_sessions(db,user,db.scalars(statement.order_by(desc(models.Session.created_at))).all())):
        if audio_status and item["audio_status"]!=audio_status:continue
        if camera_quality_max is not None and (item["metrics"]["camera_quality"] is None or item["metrics"]["camera_quality"]>camera_quality_max):continue
        if confidence_min is not None and (item["confidence"] is None or item["confidence"]<confidence_min):continue
        evidence.append(item)
    start=(max(page,1)-1)*min(page_size,100);return {"items":evidence[start:start+min(page_size,100)],"total":len(evidence),"page":max(page,1),"page_size":min(page_size,100)}

@app.post("/api/v1/notifications/generate")
def create_notifications(db:DBSession=Depends(get_db),user:Principal=Depends(require("analytics:view"))):
    rows=_accessible_sessions(db,user,select(models.Session).where(models.Session.archived.is_(False)));return {"created":generate_alerts(db,rows,user.id,settings),"advisory_only":True}

NOTIFICATION_SEVERITY = {"PROCESSING_FAILED": "CRITICAL", "POOR_CAMERA": "WARNING", "POOR_AUDIO": "WARNING", "MODEL_PROVIDER_UNAVAILABLE": "WARNING", "INSUFFICIENT_EVIDENCE": "INFO"}


def _notification_view(row, existing_session_ids: set[int]) -> dict:
    linked = row.session_id if row.session_id in existing_session_ids else None
    return {"id": row.id, "category": row.category, "severity": NOTIFICATION_SEVERITY.get(row.category, "INFO"), "title": row.title, "message": row.message, "evidence": row.evidence, "session_id": linked, "link": f"/sessions/{linked}" if linked else None, "read": row.read_at is not None, "dismissed": row.dismissed_at is not None, "created_at": row.created_at}


@app.get("/api/v1/notifications")
def notifications(response: HttpResponse, include_dismissed: bool = False, category: str | None = None, severity: str | None = None, read: bool | None = None, page: int = 1, page_size: int = 50, db: DBSession = Depends(get_db), user: Principal = Depends(require("analytics:view"))):
    """Newest first. Pagination via page/page_size; totals in X-Total-Count and X-Unread-Count. Deep links only point at sessions that still exist."""
    base = select(models.Notification).where(models.Notification.user_id == user.id)
    if not include_dismissed: base = base.where(models.Notification.dismissed_at.is_(None))
    unread = db.scalar(select(func.count()).select_from(base.where(models.Notification.read_at.is_(None)).subquery())) or 0
    statement = base
    if category: statement = statement.where(models.Notification.category == category)
    if severity:
        wanted = severity.upper()
        statement = statement.where(models.Notification.category.in_([key for key, value in NOTIFICATION_SEVERITY.items() if value == wanted] or ["__none__"]))
    if read is not None: statement = statement.where(models.Notification.read_at.is_not(None) if read else models.Notification.read_at.is_(None))
    page, page_size = max(1, page), max(1, min(200, page_size))
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    response.headers["X-Unread-Count"] = str(unread)
    rows = db.scalars(statement.order_by(desc(models.Notification.created_at), desc(models.Notification.id)).offset((page - 1) * page_size).limit(page_size)).all()
    session_ids = {row.session_id for row in rows if row.session_id}
    existing = set(db.scalars(select(models.Session.id).where(models.Session.id.in_(session_ids))).all()) if session_ids else set()
    return [_notification_view(row, existing) for row in rows]


@app.post("/api/v1/notifications/read-all")
def read_all_notifications(category: str | None = None, db: DBSession = Depends(get_db), user: Principal = Depends(require("analytics:view"))):
    """Bulk mark-as-read for the caller's own unread, non-dismissed notifications (optionally one category)."""
    statement = select(models.Notification).where(models.Notification.user_id == user.id, models.Notification.read_at.is_(None), models.Notification.dismissed_at.is_(None))
    if category: statement = statement.where(models.Notification.category == category)
    rows = db.scalars(statement).all()
    now = utc_now_naive()
    for row in rows: row.read_at = now
    db.commit()
    return {"updated": len(rows)}


@app.post("/api/v1/notifications/{notification_id}/read")
def read_notification(notification_id: int, db: DBSession = Depends(get_db), user: Principal = Depends(require("analytics:view"))):
    row = db.get(models.Notification, notification_id)
    if not row or row.user_id != user.id: raise HTTPException(404, "Notification not found")
    row.read_at = row.read_at or utc_now_naive()
    db.commit(); return {"id": row.id, "read": row.read_at is not None, "dismissed": row.dismissed_at is not None}


@app.post("/api/v1/notifications/{notification_id}/dismiss")
def dismiss_notification(notification_id: int, db: DBSession = Depends(get_db), user: Principal = Depends(require("analytics:view"))):
    row = db.get(models.Notification, notification_id)
    if not row or row.user_id != user.id: raise HTTPException(404, "Notification not found")
    row.dismissed_at = utc_now_naive(); db.commit(); return {"id": row.id, "read": row.read_at is not None, "dismissed": True}


def _can_edit_note(user, row) -> bool:
    """Authors edit their own notes; administrators edit any; notes with no recorded author (legacy/local) are editable by writers."""
    return user.role == "ADMINISTRATOR" or row.author_user_id is None or row.author_user_id == user.id


def _note_view(db, user, row, authors: dict) -> dict:
    author = authors.get(row.author_user_id)
    can_write = "*" in auth_permissions(user.role) or "note:write" in auth_permissions(user.role)
    return {"id": row.id, "scope_type": row.scope_type, "scope_id": row.scope_id, "body": row.body, "review_status": row.review_status, "version": row.version, "edited": row.version > 1, "created_at": row.created_at, "updated_at": row.updated_at, "author": {"id": row.author_user_id, "display_name": author.display_name, "role": author.role} if author else {"id": row.author_user_id, "display_name": "Local user" if row.author_user_id is None else "Unknown user", "role": None}, "can_edit": bool(can_write and _can_edit_note(user, row))}


@app.get("/api/v1/notes")
def notes(scope_type: str, scope_id: int, db: DBSession = Depends(get_db), user: Principal = Depends(require("analytics:view"))):
    probe = models.CollaborationNote(scope_type=scope_type.upper(), scope_id=scope_id)
    if not can_access_note(db, user, probe): raise HTTPException(403, "Note access denied")
    rows = db.scalars(select(models.CollaborationNote).where(models.CollaborationNote.scope_type == scope_type.upper(), models.CollaborationNote.scope_id == scope_id).order_by(models.CollaborationNote.updated_at)).all()
    author_ids = {row.author_user_id for row in rows if row.author_user_id}
    authors = {account.id: account for account in db.scalars(select(models.User).where(models.User.id.in_(author_ids))).all()} if author_ids else {}
    return [_note_view(db, user, row, authors) for row in rows]


@app.post("/api/v1/notes")
def create_note(payload: schemas.NoteCreate, db: DBSession = Depends(get_db), user: Principal = Depends(require("note:write"))):
    probe = models.CollaborationNote(scope_type=payload.scope_type, scope_id=payload.scope_id)
    if not can_access_note(db, user, probe): raise HTTPException(403, "Note access denied")
    row = models.CollaborationNote(**payload.model_dump(), author_user_id=user.id); db.add(row); db.flush(); _audit(db, user, "NOTE_CREATED", "NOTE", row.id, {"scope": payload.scope_type, "scope_id": payload.scope_id}); db.commit(); db.refresh(row)
    authors = {account.id: account for account in [db.get(models.User, user.id)] if account} if user.id else {}
    return _note_view(db, user, row, authors)


@app.put("/api/v1/notes/{note_id}")
def update_note(note_id: int, payload: schemas.NoteUpdate, db: DBSession = Depends(get_db), user: Principal = Depends(require("note:write"))):
    row = db.get(models.CollaborationNote, note_id)
    if not row: raise HTTPException(404, "Note not found")
    if not can_access_note(db, user, row): raise HTTPException(403, "Note access denied")
    if not _can_edit_note(user, row): raise _structured_error(403, "NOTE_EDIT_FORBIDDEN", "Only the note's author or an administrator can edit it.")
    if row.version != payload.version: raise HTTPException(409, "Note changed; reload before saving")
    row.body = payload.body; row.review_status = payload.review_status; row.version += 1; _audit(db, user, "NOTE_UPDATED", "NOTE", row.id, {"version": row.version}); db.commit(); db.refresh(row)
    author = db.get(models.User, row.author_user_id) if row.author_user_id else None
    return _note_view(db, user, row, {author.id: author} if author else {})


@app.get("/api/v1/aggregate-report", dependencies=[Depends(rate_limit("report"))])
def aggregate_report(course_id:int|None=None,classroom_id:int|None=None,format:str="csv",start_date:datetime|None=None,end_date:datetime|None=None,db:DBSession=Depends(get_db),user:Principal=Depends(require("export"))):
    if format not in {"csv","json","pdf"}:raise HTTPException(400,"Format must be csv, json, or pdf")
    if start_date and end_date and start_date>end_date:raise HTTPException(400,"start_date must not be after end_date")
    if course_id and not can_access_course(db,user,course_id):raise HTTPException(403,"Course access denied")
    if classroom_id and not can_access_session(db,user,models.Session(classroom_id=classroom_id)):raise HTTPException(403,"Classroom access denied")
    statement=select(models.Session)
    if course_id:statement=statement.where(models.Session.course_id==course_id)
    if classroom_id:statement=statement.where(models.Session.classroom_id==classroom_id)
    scoped=[row for row in db.scalars(statement).all() if can_access_session(db,user,row)];excluded=[{"session_id":row.id,"reason":"ARCHIVED"} for row in scoped if row.archived]
    for row in scoped:
        if not row.archived and start_date and row.created_at<start_date:excluded.append({"session_id":row.id,"reason":"BEFORE_DATE_RANGE"})
        if not row.archived and end_date and row.created_at>end_date:excluded.append({"session_id":row.id,"reason":"AFTER_DATE_RANGE"})
    rows=[row for row in scoped if not row.archived and (not start_date or row.created_at>=start_date) and (not end_date or row.created_at<=end_date)];data=aggregate_dashboard(db,rows);data.update({"scope":{"type":"COURSE" if course_id else "CLASSROOM" if classroom_id else "ACCESSIBLE","id":course_id or classroom_id},"date_range":{"start":start_date,"end":end_date,"timezone":"UTC"},"excluded_sessions":excluded,"limitations":["Aggregate descriptive evidence only; unavailable values are not zero.","Reviewer-excluded evidence is omitted from fused evidence and counted for traceability.","Transcript-derived evidence may be unavailable after retention."]});stem=f"aggregate_{course_id or classroom_id or 'all'}";path=settings.report_dir/f"{stem}.{format}"
    if format=="json":
        path.write_text(json.dumps(data,default=str,indent=2),encoding="utf-8");return FileResponse(path,media_type="application/json",filename=path.name)
    if format=="pdf":
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        document=canvas.Canvas(str(path),pagesize=letter);document.drawString(50,750,"AmbiSense aggregate evidence report");document.drawString(50,730,f"Scope: {data['scope']} | Date range: {data['date_range']}");document.drawString(50,712,f"Included sessions: {data['included_session_ids']} | Excluded: {data['excluded_sessions']}");document.drawString(50,694,f"Status: {data['status']} | Coverage: {data['average_coverage']} | Confidence: {data['average_confidence']}");document.drawString(50,676,f"Contexts: {data['contexts']} | Methodology: {data['methodology_versions']}");y=648
        for metric,envelope in data["metrics"].items():document.drawString(50,y,f"{metric}: {envelope['value']} ({envelope['available_sessions']}/{envelope['total_sessions']} sessions)");y-=18
        document.drawString(50,max(y-10,80),"Advisory aggregate evidence only; not an individual or causal conclusion.");document.save();return FileResponse(path,media_type="application/pdf",filename=path.name)
    with path.open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=["scope","date_range","included_session_ids","excluded_sessions","metric","value","available_sessions","total_sessions","average_coverage","average_confidence","contexts","methodology_versions","reviewer_excluded_evidence","limitations"]);writer.writeheader()
        for metric,envelope in data["metrics"].items():writer.writerow({"scope":str(data["scope"]),"date_range":str(data["date_range"]),"included_session_ids":str(data["included_session_ids"]),"excluded_sessions":str(data["excluded_sessions"]),"metric":metric,**envelope,"average_coverage":data["average_coverage"],"average_confidence":data["average_confidence"],"contexts":str(data["contexts"]),"methodology_versions":str(data["methodology_versions"]),"reviewer_excluded_evidence":data["reviewer_excluded_evidence"],"limitations":" | ".join(data["limitations"]+[x["text"] for x in data["common_limitations"]])})
    return FileResponse(path,media_type="text/csv",filename=path.name)


@app.websocket("/ws/analytics/{session_id}")
@app.websocket("/ws/sessions/{session_id}")
async def websocket_analytics(websocket: WebSocket, session_id: int):
    with SessionLocal() as auth_db:
        try:
            token=websocket.query_params.get("access_token");uid=websocket.query_params.get("user_id");user=resolve_principal(f"Bearer {token}" if token else None,int(uid) if uid and uid.isdigit() else None,auth_db);target=auth_db.get(models.Session,session_id)
            if target and not can_access_session(auth_db,user,target):raise HTTPException(403,"Session access denied")
        except HTTPException:
            await websocket.close(code=1008);return
    await websocket.accept()
    sequence = 0
    try:
        while True:
            sequence += 1
            with SessionLocal() as db:
                row = db.scalar(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id == session_id).order_by(desc(models.AnalyticsSnapshot.timestamp)))
                session = db.get(models.Session, session_id)
                await websocket.send_json({"type": "snapshot", "sequence": sequence, "server_time": utc_iso_z(), "session_id": session_id, "status": session.status if session else "NOT_FOUND", "stage": session.processing_stage if session else "NOT_FOUND", "progress": session.progress if session else 0, "processed_frames": session.processed_frames if session else 0, "total_frames": session.total_frames if session else 0, "processing_speed": session.processing_speed if session else 0, "latency_ms": None, "eta_seconds": session.eta_seconds if session else 0, "analytics": None if not row else {"timestamp": row.timestamp, "student_count": row.student_count, "occupancy_rate": row.occupancy_rate, "estimated_unique_tracks": row.estimated_unique_tracks, "verified_attendance_rate": None, "metrics": row.details.get("metrics", {}), "attention": row.attention_score, "engagement": row.engagement_score, "drowsiness": row.drowsiness_count, "fatigue": row.fatigue_score, "yawning": row.yawning_count, "raised_hands": row.raised_hands, "distracted_students": row.distracted_students, "occupied_seats": row.occupied_seats, "empty_seats": row.empty_seats, "events": [], "mode": row.details.get("mode", "REAL")}})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)


@app.websocket("/ws/live/{session_id}")
async def websocket_live_frames(websocket: WebSocket, session_id: int):
    """Receive real browser-camera JPEG frames, persist CV evidence, and write annotated output."""
    with SessionLocal() as db:
        try:
            token=websocket.query_params.get("access_token");uid=websocket.query_params.get("user_id");user=resolve_principal(f"Bearer {token}" if token else None,int(uid) if uid and uid.isdigit() else None,db);target=db.get(models.Session,session_id)
            if target and not can_access_session(db,user,target):raise HTTPException(403,"Session access denied")
            if user.role not in {"ADMINISTRATOR","INSTRUCTOR"}:raise HTTPException(403,"Live processing permission denied")
        except HTTPException:
            await websocket.close(code=1008);return
        await websocket.accept()
        session = db.get(models.Session, session_id)
        if not session:
            await websocket.send_json({"error": "Session not found"}); await websocket.close(code=1008); return
        if session.source_type!="LIVE":
            await websocket.send_json({"error":"Session is not a live-camera session"});await websocket.close(code=1008);return
        session.status = "INITIALIZING"; session.processing_stage = "LOADING_MODELS"; session.analytics_mode = "REAL"; session.started_at = session.started_at or utc_now_naive();session.error=None;session.failure_code=None;db.commit()
    logger.info("[BACKEND] Live session %s accepted; loading models",session_id)
    from ultralytics import YOLO
    detector=None;face_processor=None;pose_processor=None;writer=None;processor=VideoProcessor(session_id,"",settings);started=time.perf_counter();frame_count=0;explicit_stop=False;output=settings.report_dir/f"annotated_live_{session_id}.mp4"
    live_connection_opened(session_id)
    try:
        detector=YOLO(settings.yolo_model);face_processor=FaceLandmarkProcessor(Path(settings.face_landmarker_model));pose_processor=PoseProcessor(Path(settings.pose_landmarker_model))
        with SessionLocal() as db:
            session=db.get(models.Session,session_id);session.status="PROCESSING";session.processing_stage="CAPTURING_LIVE_CAMERA";db.commit()
        await websocket.send_json({"type":"status","stage":"CAPTURING_LIVE_CAMERA","message":"Models loaded; waiting for camera frames"})
        while True:
            message=await websocket.receive()
            if message.get("type")=="websocket.disconnect":break
            if message.get("text"):
                if message["text"]=="STOP":explicit_stop=True;logger.info("[SESSION] Live session %s received explicit stop",session_id);break
                if message["text"]=="PING":await websocket.send_json({"type":"pong","session_id":session_id,"timestamp":utc_iso_z()})
                continue
            encoded=message.get("bytes")
            if not encoded:continue
            if frame_count == 0 or frame_count % 20 == 0:
                logger.info("[BACKEND] Frame received for session %s (%s bytes)",session_id,len(encoded))
            frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                await websocket.send_json({"error": "Invalid camera frame"}); continue
            timestamp = time.perf_counter() - started; frame_count += 1; timestamp_ms = int(timestamp * 1000)
            if writer is None:
                height,width=frame.shape[:2];writer=cv2.VideoWriter(str(output),cv2.VideoWriter_fourcc(*"mp4v"),2.0,(width,height))
                if not writer.isOpened():raise RuntimeError("Live annotated-video writer could not be opened")
                with SessionLocal() as db:
                    session=db.get(models.Session,session_id);session.fps=2.0;session.annotated_video_path=str(output);db.commit()
                logger.info("[CAMERA] First live frame %sx%s; annotated writer opened for session %s",width,height,session_id)
            inference_started=time.perf_counter()
            if frame_count == 1 or frame_count % 20 == 0:
                logger.info("[PROCESSING] Detection started for session %s frame %s",session_id,frame_count)
            result = detector.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml", conf=settings.yolo_confidence, device=processor.device, verbose=False)[0]
            faces = face_processor.process(frame, timestamp_ms); poses = pose_processor.process(frame, timestamp_ms)
            with SessionLocal() as db:
                observations = processor._observations(db, result, faces, poses, timestamp)
                processor._aggregate(db, timestamp, observations)
                quality=assess_frame_quality(frame,people=len(observations),face_count=len(faces),pose_count=len(poses));db.add(models.QualityAssessment(session_id=session_id,timestamp=round(timestamp,3),overall_quality=quality.get("overall_quality"),status=quality["status"],details=quality))
                session = db.get(models.Session, session_id); session.processed_frames = frame_count;session.total_frames=frame_count;session.duration=round(timestamp,2);session.progress=0; session.processing_speed = round(frame_count / max(timestamp, .001), 2); db.commit()
                snapshot = db.scalar(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id == session_id).order_by(desc(models.AnalyticsSnapshot.id)))
                metric_details = snapshot.details.get("metrics", {}) if snapshot else {}
                occupancy_rate = snapshot.occupancy_rate if snapshot else None
                if frame_count == 1 or frame_count % 20 == 0:
                    logger.info("[DATABASE] Session %s frame %s observations=%s snapshot=%s quality=%s",session_id,frame_count,len(observations),snapshot.id if snapshot else None,quality["status"])
            annotated = frame.copy()
            if settings.show_overlays:
                for observation in observations: processor._draw(annotated, observation)
            writer.write(annotated)
            ok, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
            count = len(observations); attention = sum(row["attention_score"] for row in observations) / count if count else 0
            latency=round((time.perf_counter()-inference_started)*1000,1)
            if frame_count == 1 or frame_count % 20 == 0:
                logger.info("[PROCESSING] Detection completed for session %s frame %s in %sms",session_id,frame_count,latency)
            capacity=max(0,settings.total_seats);empty=max(0,capacity-count);fps=round(frame_count/max(timestamp,.001),2)
            # frame_quality reuses the same canonical helper as the REST
            # /quality endpoint and session comparison, fed with this one
            # frame's just-computed quality dict wrapped in a row-like
            # object (avoids an extra QualityAssessment query per frame).
            frame_quality=frame_quality_metric([SimpleNamespace(overall_quality=quality.get("overall_quality"))],quality.get("overall_quality"),quality.get("warnings",[]))
            live_metrics={"occupancy":metric_envelope("occupancy",count,valid_observations=1,eligible_observations=1,confidence=sum(row["confidence"] for row in observations)/count if count else 0,unit="count"),**metric_details,"prolonged_eye_closure":metric_envelope("prolonged_eye_closure",sum(row["drowsiness"] for row in observations),valid_observations=len([row for row in observations if row["ear"] is not None]),eligible_observations=count,unit="count"),"yawning":metric_envelope("yawning",sum(row["yawning"] for row in observations),valid_observations=len([row for row in observations if row["mar"] is not None]),eligible_observations=count,unit="count"),"raised_hands":metric_envelope("raised_hands",sum(row["raised_hand"] for row in observations),valid_observations=len(poses),eligible_observations=count,unit="count"),"unoccupied_capacity":metric_envelope("unoccupied_capacity",empty,valid_observations=1,eligible_observations=1,unit="count"),"frame_quality":frame_quality}
            # Wire format is the canonical MetricAvailability contract only
            # (value/available/reason/coverage/confidence/valid_observations/
            # total_observations) - internal-only fields like `status` and
            # `limitations` are stripped at this boundary.
            canonical_metrics={key:as_metric_availability(value) for key,value in live_metrics.items()}
            await websocket.send_json({"type":"live_metrics","session_id":session_id,"sequence":frame_count,"timestamp":utc_iso_z(),"pipeline":{"camera_connected":True,"frames_transmitting":True,"backend_receiving":True,"models_loaded":True,"inference_running":True,"metrics_aggregating":bool(snapshot),"live_updates_connected":True},"transport":{"fps":fps,"latency_ms":latency,"frames_received":frame_count,"frames_processed":frame_count},"metrics":canonical_metrics,"student_count":count,"occupancy_rate":occupancy_rate,"attention":round(attention,2),"raised_hands":sum(row["raised_hand"] for row in observations),"drowsiness":sum(row["drowsiness"] for row in observations),"yawning":sum(row["yawning"] for row in observations),"empty_seats":empty,"annotated_image":base64.b64encode(jpeg).decode() if ok else None,"privacy_mode":settings.privacy_mode})
    except WebSocketDisconnect:
        logger.info("Live camera disconnected for session %s", session_id)
    except Exception as error:
        reference=uuid.uuid4().hex[:12];logger.exception("Live processing failed for session %s [%s]",session_id,reference)
        with SessionLocal() as db:
            session=db.get(models.Session,session_id);session.status="FAILED";session.processing_stage="FAILED";session.error="Live camera processing failed";session.failure_code="LIVE_PROCESSING_FAILED";session.internal_error_reference=reference;session.ended_at=utc_now_naive();db.commit()
        try:await websocket.send_json({"error":"Live processing failed","reference":reference})
        except Exception:pass
    finally:
        live_connection_closed(session_id)
        if writer:writer.release()
        if face_processor:face_processor.close()
        if pose_processor:pose_processor.close()
        with SessionLocal() as db:
            session=db.get(models.Session,session_id)
            if session and session.status!="FAILED":
                processor._persist_tracks(db);session.ended_at=utc_now_naive();session.processed_frames=frame_count;session.total_frames=frame_count;session.duration=round(time.perf_counter()-started,2);session.progress=100 if explicit_stop and frame_count else 0
                if explicit_stop and frame_count:
                    session.status="GENERATING_REPORT";session.processing_stage="GENERATING_REPORT";session.annotated_video_path=str(output);db.commit()
                    for report_format,factory in (("csv",create_csv_report),("pdf",create_pdf_report),("metrics",create_metrics_csv_report)):
                        upsert_report(db,session_id,report_format,factory(db,session_id))
                    session.status="COMPLETED";session.processing_stage="COMPLETED";db.commit()
                else:
                    session.status="STOPPED";session.processing_stage="STOPPED";session.error="Camera stream ended before explicit completion" if not frame_count else None;db.commit()
                logger.info("[SESSION] Live session %s finalized status=%s frames=%s",session_id,session.status,frame_count)
