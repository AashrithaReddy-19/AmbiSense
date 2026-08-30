import logging
import math
import time
import uuid
from datetime import datetime
from pathlib import Path

import cv2
import torch
from sqlalchemy import delete, select

from .. import models

from ..config import Settings, get_settings
from ..cv.attention import AttentionEstimator
from ..cv.drowsiness import DrowsinessDetector
from ..cv.engagement import calculate_engagement, calculate_fatigue
from ..cv.face_landmarks import FaceLandmarkProcessor, FaceSignals
from ..cv.pose import PoseProcessor, PoseSignals
from ..cv.yawn import YawnDetector
from ..cv.tracking import TrackLifecycleManager
from ..cv.quality import assess_frame_quality
from ..cv.regions import assign_region
from ..metrics import bounded_percentage, metric_envelope, safe_rate
from .activity_context import context_limitations, metric_relevant
from .report_generator import create_csv_report, create_pdf_report
from ..database import SessionLocal
from ..models import Alert, AnalyticsSnapshot, AnonymousTrack, Event, QualityAssessment, Session, StudentObservation


logger = logging.getLogger("ambisense.processor")


class VideoProcessor:
    """Run demo or real anonymous CV analytics and generate an annotated video."""

    def __init__(self, session_id: int, video_path: str, settings: Settings | None = None):
        self.session_id = session_id
        self.video_path = Path(video_path)
        self.settings = settings or get_settings()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.attention = AttentionEstimator(self.settings.ema_alpha)
        self.drowsiness = DrowsinessDetector(self.settings.ear_threshold, self.settings.drowsiness_duration)
        self.yawning = YawnDetector(self.settings.yawn_threshold, self.settings.yawn_min_duration)
        self.tracks = TrackLifecycleManager(self.settings.minimum_track_observations, self.settings.minimum_track_duration, self.settings.track_timeout, self.settings.track_reentry_window, self.settings.track_iou_gate)
        self.peak_occupancy = 0
        self.non_attentive_since: dict[str, float] = {}
        self.hand_states: dict[str, bool] = {}
        self.last_event_at: dict[str, float] = {}
        self._layout_regions = None

    def run(self) -> None:
        db = SessionLocal()
        session = db.get(Session, self.session_id)
        if not session:
            db.close(); return
        if session.status in {"PROCESSING", "INITIALIZING", "FINALIZING", "COMPLETED"}: db.close(); return
        session.status = "DECODING"; session.processing_stage = "DECODING"; session.started_at = session.started_at or datetime.utcnow(); session.error = None
        session.analytics_mode = "DEMO" if self.settings.demo_mode else "REAL"
        db.commit(); logger.info("[JOB] stage=DECODING session_id=%s job_id=%s", self.session_id, session.job_id)
        try:
            # A retry replaces only incomplete derived records for this job.
            for model in (StudentObservation, AnalyticsSnapshot, Event, Alert, AnonymousTrack, QualityAssessment):
                db.execute(delete(model).where(model.session_id == self.session_id))
            session.status = "PROCESSING"; session.processing_stage = "PROCESSING"; db.commit(); logger.info("[JOB] stage=PROCESSING session_id=%s job_id=%s", self.session_id, session.job_id)
            if self.settings.demo_mode: self._run_demo(db, session)
            else: self._run_real(db, session)
            session.status = "AGGREGATING"; session.processing_stage = "AGGREGATING"; db.commit(); logger.info("[JOB] stage=AGGREGATING session_id=%s job_id=%s", self.session_id, session.job_id)
            self._persist_tracks(db)
            try:
                from .audio_intelligence import run_audio_intelligence
                session.processing_stage = "AUDIO_INTELLIGENCE"; db.commit()
                run_audio_intelligence(db, session, self.settings)
            except Exception:
                # Audio is optional and must never invalidate completed visual evidence.
                logger.exception("Optional audio intelligence failed for session %s", self.session_id)
                db.rollback()
                row = db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id == self.session_id))
                if not row: db.add(models.AudioAnalysis(session_id=self.session_id, status="FAILED", limitations=["Optional audio processing failed; visual analytics remain available."]))
                else: row.status="FAILED"; row.limitations=[*row.limitations,"Optional audio processing failed; visual analytics remain available."]
                db.commit()
            session.status = "GENERATING_REPORT"; session.processing_stage = "GENERATING_REPORT"; db.commit(); logger.info("[REPORT] generation started session_id=%s job_id=%s", self.session_id, session.job_id)
            for report_format, factory in (("csv", create_csv_report), ("pdf", create_pdf_report)):
                path = factory(db, self.session_id)
                report = db.scalar(select(models.Report).where(models.Report.session_id == self.session_id, models.Report.format == report_format))
                if report: report.path = str(path)
                else: db.add(models.Report(session_id=self.session_id, format=report_format, path=str(path)))
            db.commit(); logger.info("[REPORT] generation completed session_id=%s job_id=%s", self.session_id, session.job_id)
            session.status = "COMPLETED"; session.processing_stage = "COMPLETED"; session.progress = 100; session.eta_seconds = 0; session.ended_at = datetime.utcnow()
            db.commit(); logger.info("[JOB] stage=COMPLETED session_id=%s job_id=%s", self.session_id, session.job_id)
        except Exception as error:
            logger.exception("Session %s processing failed", self.session_id)
            reference = uuid.uuid4().hex[:12]
            failure_code = "VIDEO_DECODING_FAILED" if isinstance(error, ValueError) else "MODEL_OR_PROCESSING_FAILED"
            session.status = "FAILED"; session.processing_stage = "FAILED"; session.error = f"{str(error)[:240] or 'Video processing failed'} (reference {reference})"; session.failure_code = failure_code; session.internal_error_reference = reference; session.ended_at = datetime.utcnow(); db.commit()
            logger.error("[JOB] stage=FAILED session_id=%s job_id=%s code=%s reference=%s", self.session_id, session.job_id, failure_code, reference)
        finally:
            db.close()

    def _metadata(self, session: Session):
        capture = cv2.VideoCapture(str(self.video_path))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)); fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)); height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not capture.isOpened() or frames <= 0 or fps <= 0 or width <= 0 or height <= 0:
            capture.release(); raise ValueError("Invalid or unsupported video")
        session.duration = frames / fps; session.fps = fps; session.total_frames = frames
        return capture, frames, fps, width, height

    def _run_demo(self, db, session: Session) -> None:
        capture, frames, fps, _width, _height = self._metadata(session); capture.release()
        points = max(6, min(120, math.ceil(session.duration / 5)))
        for index in range(points):
            timestamp = min(session.duration, index * session.duration / max(points - 1, 1)); wave = math.sin(index / 4)
            students = max(1, round(28 + wave * 3)); attention = max(30, min(95, 73 + wave * 9 - index * .08)); drowsy = max(0, round(2 + index / points * 3 - wave)); yawns = index // 8
            fatigue = float(calculate_fatigue(drowsy / students * 100, yawns * 2, 100 - attention, max(0, 75 - attention))["fatigue_score"])
            engagement = float(calculate_engagement({"attention": attention, "orientation": attention + 3, "eye_state": 100 - drowsy / students * 100, "activity": 70, "expression": 65})["engagement_score"])
            self._snapshot(db, timestamp, students, attention, engagement, fatigue, drowsy, yawns, "DEMO")
            session.processed_frames = round((index + 1) / points * frames); session.progress = round((index + 1) / points * 100, 2); db.commit()

    def _run_real(self, db, session: Session) -> None:
        from ultralytics import YOLO

        capture, total_frames, fps, width, height = self._metadata(session)
        output = self.settings.report_dir / f"annotated_{self.session_id}.mp4"
        writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened(): capture.release(); raise RuntimeError("Annotated video writer could not be opened")
        model = YOLO(self.settings.yolo_model)
        landmarker = FaceLandmarkProcessor(Path(self.settings.face_landmarker_model))
        pose_processor = PoseProcessor(Path(self.settings.pose_landmarker_model))
        started = time.perf_counter(); frame_index = 0; sampled = 0; cached = []
        try:
            while True:
                ok, frame = capture.read()
                if not ok: break
                timestamp = frame_index / fps
                if frame_index % self.settings.process_every_n_frames == 0:
                    sampled += 1
                    result = model.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml", conf=self.settings.yolo_confidence, device=self.device, verbose=False)[0]
                    faces = landmarker.process(frame, int(timestamp * 1000))
                    poses = pose_processor.process(frame, int(timestamp * 1000))
                    cached = self._observations(db, result, faces, poses, timestamp)
                    self._aggregate(db, timestamp, cached)
                    quality = assess_frame_quality(frame, people=len(cached), face_count=len(faces), pose_count=len(poses))
                    db.add(QualityAssessment(session_id=self.session_id,timestamp=round(timestamp,3),overall_quality=quality.get("overall_quality"),status=quality["status"],details=quality))
                annotated = frame.copy()
                for observation in cached: self._draw(annotated, observation)
                latest = cached
                cv2.rectangle(annotated, (0, 0), (width, 42), (8, 16, 28), -1)
                attentive = sum(item["attention_score"] for item in latest) / len(latest) if latest else 0
                cv2.putText(annotated, f"Students: {len(latest)}  Estimated visual attention: {attentive:.0f}%  Mode: REAL", (12, 27), cv2.FONT_HERSHEY_SIMPLEX, .58, (49, 216, 160), 2)
                writer.write(annotated)
                frame_index += 1; elapsed = max(time.perf_counter() - started, .001); speed = frame_index / elapsed
                session.processed_frames = frame_index; session.progress = round(frame_index / total_frames * 100, 2); session.processing_speed = round(speed, 2); session.eta_seconds = round((total_frames - frame_index) / max(speed, .001), 2)
                if frame_index % max(1, int(fps)) == 0: db.commit()
            session.processing_stage = "GENERATING_ANALYTICS"; session.annotated_video_path = str(output); db.commit()
        finally:
            landmarker.close(); pose_processor.close(); capture.release(); writer.release()

    def _observations(self, db, result, faces: list[FaceSignals], poses: list[PoseSignals], timestamp: float) -> list[dict]:
        observations = []
        if self._layout_regions is None:
            session = db.get(Session, self.session_id)
            layout = db.scalar(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id == session.classroom_id, models.ClassroomLayout.active.is_(True)).order_by(models.ClassroomLayout.version.desc())) if session and session.classroom_id else None
            self._layout_regions = list(layout.regions) if layout else []
        boxes = result.boxes
        if boxes is None: return observations
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else list(range(1, len(boxes) + 1))
        for index, coordinates in enumerate(boxes.xyxy.cpu().tolist()):
            x1, y1, x2, y2 = coordinates
            confidence = float(boxes.conf[index].item()); track=self.tracks.observe(int(ids[index]),timestamp,confidence,coordinates); tracking_id=f"Track_{track.uuid[:8]}"
            height, width = result.orig_shape; region_id = assign_region(((x1+x2)/2, (y1+y2)/2), width, height, self._layout_regions)
            face = next((item for item in faces if x1 <= item.center[0] <= x2 and y1 <= item.center[1] <= y2), None)
            pose_signal = next((item for item in poses if x1 <= item.center[0] <= x2 and y1 <= item.center[1] <= y2), None)
            pose = face.head_pose if face else None; direction = pose.direction if pose else "UNKNOWN"
            attention = self.attention.estimate(tracking_id, direction)
            eye = self.drowsiness.update(tracking_id, face.ear, timestamp) if face else {"eye_state": "UNKNOWN", "possible_drowsiness": False}
            yawn = self.yawning.update(tracking_id, face.mar, timestamp) if face else {"yawning": False, "yawn_count": self.yawning.counts.get(tracking_id, 0)}
            state = str(attention["state"])
            if state not in {"ATTENTIVE", "UNKNOWN"}:
                self.non_attentive_since.setdefault(tracking_id, timestamp)
                if timestamp - self.non_attentive_since[tracking_id] >= self.settings.distraction_min_duration:
                    state = "DISTRACTED"
            else:
                self.non_attentive_since.pop(tracking_id, None)
            raised_hand = bool(pose_signal and pose_signal.raised_hand)
            previous_hand = self.hand_states.get(tracking_id, False)
            if raised_hand != previous_hand:
                event_type = "HAND_RAISED" if raised_hand else "HAND_LOWERED"
                event_key=f"{tracking_id}:{event_type}"
                if timestamp-self.last_event_at.get(event_key,-999)>=1.5:
                    db.add(Event(session_id=self.session_id, timestamp=timestamp, end_timestamp=timestamp, tracking_id=tracking_id, event_type=event_type, severity="INFO", message=f"{tracking_id}: hand {'raised' if raised_hand else 'lowered'}", confidence=pose_signal.confidence if pose_signal else 0, region_id=region_id, affected_tracks=1, details={"confidence": pose_signal.confidence if pose_signal else 0}))
                    self.last_event_at[event_key]=timestamp
            self.hand_states[tracking_id] = raised_hand
            item = {"tracking_id": tracking_id, "region_id": region_id, "bbox": [round(v, 1) for v in coordinates], "confidence": confidence, "yaw": pose.yaw if pose else None, "pitch": pose.pitch if pose else None, "roll": pose.roll if pose else None, "direction": direction, "attention_state": state, "attention_score": float(attention["score"]), "ear": face.ear if face else None, "eye_state": eye["eye_state"], "drowsiness": bool(eye["possible_drowsiness"]), "mar": face.mar if face else None, "yawning": bool(yawn["yawning"]), "yawn_count": int(yawn["yawn_count"]), "raised_hand": raised_hand}
            observations.append(item)
            db.add(StudentObservation(session_id=self.session_id, timestamp=round(timestamp, 3), tracking_id=tracking_id, confidence=confidence, bbox=item["bbox"], yaw=item["yaw"], pitch=item["pitch"], roll=item["roll"], head_direction=direction, attention_state=item["attention_state"], attention_score=item["attention_score"], ear=item["ear"], eye_state=item["eye_state"], possible_drowsiness=item["drowsiness"], mar=item["mar"], yawning=item["yawning"], raised_hand=raised_hand, region_id=region_id))
            for active,event_type,severity,message in ((item["drowsiness"],"POSSIBLE_DROWSINESS","WARNING",f"{tracking_id}: possible prolonged eye closure"),(item["yawning"],"YAWNING","INFO",f"{tracking_id}: sustained mouth opening detected")):
                event_key=f"{tracking_id}:{event_type}"
                if active and timestamp-self.last_event_at.get(event_key,-999)>=self.settings.aggregation_interval:
                    db.add(Event(session_id=self.session_id,timestamp=timestamp,end_timestamp=timestamp,tracking_id=tracking_id,event_type=event_type,severity=severity,message=message,confidence=confidence,region_id=region_id,affected_tracks=1))
                    self.last_event_at[event_key]=timestamp
        return observations

    def _aggregate(self, db, timestamp: float, rows: list[dict]) -> None:
        count = len(rows); face_rows=[row for row in rows if row["direction"]!="UNKNOWN"]; attention = sum(row["attention_score"] for row in face_rows) / len(face_rows) if face_rows else None
        drowsy = sum(row["drowsiness"] for row in rows); yawns = sum(self.yawning.counts.values()); looking_down = sum(row["attention_state"] == "LOOKING_DOWN" for row in rows) / count * 100 if count else 0
        raised_hands = sum(row["raised_hand"] for row in rows); looking_down_count = sum(row["attention_state"] == "LOOKING_DOWN" for row in rows); looking_away_count = sum(row["attention_state"] in {"LOOKING_LEFT", "LOOKING_RIGHT", "LOOKING_AWAY", "DISTRACTED"} for row in rows)
        orientation = safe_rate(sum(row["direction"] == "FRONT" for row in face_rows),len(face_rows)); eye_score = safe_rate(len(face_rows)-drowsy,len(face_rows))
        signals={"attention":attention,"orientation":orientation,"eye_state":eye_score,"activity":safe_rate(count,self.settings.expected_students)}
        available={key:value for key,value in signals.items() if value is not None}
        engagement = float(calculate_engagement(available, {key:{"attention":.45,"orientation":.20,"eye_state":.15,"activity":.20}[key] for key in available})["engagement_score"]) if available else 0
        fatigue = float(calculate_fatigue(safe_rate(drowsy,len(face_rows)) or 0, min(100, yawns * 5), looking_down, max(0, 70 - engagement))["fatigue_score"])
        self._snapshot(db, timestamp, count, attention or 0, engagement, fatigue, drowsy, yawns, "REAL", raised_hands, looking_down_count, looking_away_count, valid_faces=len(face_rows))
        conditions = [
            (looking_away_count >= max(3, count * .3), "HIGH_DISTRACTION", "WARNING", f"{looking_away_count} students were estimated as distracted or looking away."),
            (count and (safe_rate(count,self.settings.total_seats) or 0) < 60, "LOW_OCCUPANCY", "WARNING", "Current anonymous occupancy fell below 60% of configured capacity."),
            (fatigue >= 65, "HIGH_FATIGUE", "WARNING", "Classroom fatigue indicators reached HIGH."),
            (engagement < 40, "LOW_ENGAGEMENT", "WARNING", "Estimated Engagement Index fell below 40."),
            (engagement >= 80, "HIGH_ENGAGEMENT", "INFO", "Estimated Engagement Index exceeded 80."),
            (drowsy >= max(2, count * .2), "DROWSINESS_CLUSTER", "WARNING", f"Possible prolonged eye closure detected for {drowsy} students."),
            (yawns >= 3, "YAWN_CLUSTER", "INFO", f"Classroom yawn count reached {yawns}."),
        ]
        for active, event_type, severity, message in conditions:
            if active and timestamp - self.last_event_at.get(event_type, -999) >= self.settings.aggregation_interval:
                db.add(Event(session_id=self.session_id, timestamp=timestamp, event_type=event_type, severity=severity, message=message, details={"student_count": count, "engagement": engagement, "fatigue": fatigue}))
                self.last_event_at[event_type] = timestamp

    def _snapshot(self, db, timestamp, students, attention, engagement, fatigue, drowsy, yawns, mode, raised_hands=0, looking_down=0, looking_away=0, valid_faces=None):
        expected = max(1, self.settings.expected_students); seats = max(1, self.settings.total_seats); occupied = min(seats, students); distracted = round(students * max(0, 100 - attention) / 100)
        self.peak_occupancy=max(self.peak_occupancy,occupied); faces=students if valid_faces is None else valid_faces
        coverage=safe_rate(faces,students)
        session=db.get(Session,self.session_id); activity=session.activity_context if session else "LECTURE"
        metrics={"visual_orientation":metric_envelope("visual_orientation",attention,valid_observations=faces,eligible_observations=students,confidence=(coverage or 0)/100,limitations=([] if faces else ["No usable face landmarks were available."])+context_limitations(activity,"visual_orientation"),model_enabled=metric_relevant(activity,"visual_orientation"),minimum_coverage=self.settings.minimum_metric_coverage),"observable_participation":metric_envelope("observable_participation",engagement,valid_observations=max(faces,students),eligible_observations=students,confidence=max((coverage or 0)/100,.3) if students else 0,limitations=context_limitations(activity,"observable_participation"),model_enabled=metric_relevant(activity,"observable_participation"),minimum_coverage=self.settings.minimum_metric_coverage),"possible_fatigue":metric_envelope("possible_fatigue",fatigue,valid_observations=faces,eligible_observations=students,confidence=(coverage or 0)/100,model_enabled=metric_relevant(activity,"possible_fatigue"),minimum_coverage=self.settings.minimum_metric_coverage)}
        db.add(AnalyticsSnapshot(session_id=self.session_id, timestamp=round(timestamp, 2), student_count=students, visible_faces=faces, attendance=0, attention_score=bounded_percentage(attention) or 0, engagement_score=bounded_percentage(engagement) or 0, fatigue_score=bounded_percentage(fatigue) or 0, drowsiness_count=drowsy, yawning_count=yawns, occupied_seats=occupied, empty_seats=max(0, seats - occupied), current_occupancy_count=occupied,peak_occupancy_count=self.peak_occupancy,occupancy_rate=safe_rate(occupied,seats),estimated_unique_tracks=self.tracks.valid_unique_count() if mode=="REAL" else students,verified_attendance_rate=None,noise_level="UNKNOWN", distracted_students=distracted, raised_hands=raised_hands, looking_down_students=looking_down, looking_away_students=looking_away, details={"mode": mode, "identity": "anonymous", "activity_context":activity,"metrics":metrics,"expected_students":expected,"room_capacity":seats}))
        if engagement < 40: db.add(Alert(session_id=self.session_id, timestamp=timestamp, severity="WARNING", message="Estimated engagement fell below 40%."))

    def _persist_tracks(self, db):
        for track in {item.uuid:item for item in self.tracks.tracks.values()}.values():
            db.add(AnonymousTrack(session_id=self.session_id,track_uuid=track.uuid,tracker_local_id=track.local_id,first_seen=track.first_seen,last_seen=track.last_seen,observation_count=track.observations,visible_duration=track.visible_duration,average_confidence=track.average_confidence,last_bbox=track.bbox,active=track.active,expiry_reason=track.expiry_reason))

    @staticmethod
    def _draw(frame, row):
        x1, y1, x2, y2 = (int(value) for value in row["bbox"]); color = (60, 205, 130) if row["attention_state"] == "ATTENTIVE" else (50, 170, 255)
        if row["drowsiness"]: color = (70, 70, 245)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        labels = [row["tracking_id"], row["attention_state"], row["direction"]]
        if row["drowsiness"]: labels.append("POSSIBLE DROWSINESS")
        if row["yawning"]: labels.append("YAWNING")
        if row.get("raised_hand"): labels.append("HAND RAISED")
        for line, label in enumerate(labels): cv2.putText(frame, label, (x1, max(15, y1 - 8 - line * 17)), cv2.FONT_HERSHEY_SIMPLEX, .43, color, 1, cv2.LINE_AA)
