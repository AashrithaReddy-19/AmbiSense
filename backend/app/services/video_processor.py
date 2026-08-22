import logging
import math
import time
from datetime import datetime
from pathlib import Path

import cv2
import torch

from ..config import Settings, get_settings
from ..cv.attention import AttentionEstimator
from ..cv.drowsiness import DrowsinessDetector
from ..cv.engagement import calculate_engagement, calculate_fatigue
from ..cv.face_landmarks import FaceLandmarkProcessor, FaceSignals
from ..cv.pose import PoseProcessor, PoseSignals
from ..cv.yawn import YawnDetector
from ..database import SessionLocal
from ..models import Alert, AnalyticsSnapshot, Event, RuntimeSetting, Session, StudentObservation


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
        self.observed_ids: set[str] = set()
        self.non_attentive_since: dict[str, float] = {}
        self.hand_states: dict[str, bool] = {}
        self.last_event_at: dict[str, float] = {}

    def run(self) -> None:
        db = SessionLocal()
        session = db.get(Session, self.session_id)
        if not session:
            db.close(); return
        session.status = "PROCESSING"; session.processing_stage = "ANALYZING_FRAMES"; session.started_at = datetime.utcnow()
        session.analytics_mode = "DEMO" if self.settings.demo_mode else "REAL"
        db.commit()
        try:
            if self.settings.demo_mode: self._run_demo(db, session)
            else: self._run_real(db, session)
            session.status = "COMPLETED"; session.processing_stage = "COMPLETED"; session.progress = 100; session.eta_seconds = 0; session.ended_at = datetime.utcnow()
            db.commit()
        except Exception as error:
            logger.exception("Session %s processing failed", self.session_id)
            session.status = "FAILED"; session.processing_stage = "FAILED"; session.error = str(error); session.ended_at = datetime.utcnow(); db.commit()
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
        boxes = result.boxes
        if boxes is None: return observations
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else list(range(1, len(boxes) + 1))
        for index, coordinates in enumerate(boxes.xyxy.cpu().tolist()):
            x1, y1, x2, y2 = coordinates; tracking_id = f"Student_{ids[index]:02d}"; self.observed_ids.add(tracking_id)
            confidence = float(boxes.conf[index].item()); face = next((item for item in faces if x1 <= item.center[0] <= x2 and y1 <= item.center[1] <= y2), None)
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
                db.add(Event(session_id=self.session_id, timestamp=timestamp, tracking_id=tracking_id, event_type=event_type, severity="INFO", message=f"{tracking_id}: hand {'raised' if raised_hand else 'lowered'}", details={"confidence": pose_signal.confidence if pose_signal else 0}))
            self.hand_states[tracking_id] = raised_hand
            item = {"tracking_id": tracking_id, "bbox": [round(v, 1) for v in coordinates], "confidence": confidence, "yaw": pose.yaw if pose else None, "pitch": pose.pitch if pose else None, "roll": pose.roll if pose else None, "direction": direction, "attention_state": state, "attention_score": float(attention["score"]), "ear": face.ear if face else None, "eye_state": eye["eye_state"], "drowsiness": bool(eye["possible_drowsiness"]), "mar": face.mar if face else None, "yawning": bool(yawn["yawning"]), "yawn_count": int(yawn["yawn_count"]), "raised_hand": raised_hand}
            observations.append(item)
            db.add(StudentObservation(session_id=self.session_id, timestamp=round(timestamp, 3), tracking_id=tracking_id, confidence=confidence, bbox=item["bbox"], yaw=item["yaw"], pitch=item["pitch"], roll=item["roll"], head_direction=direction, attention_state=item["attention_state"], attention_score=item["attention_score"], ear=item["ear"], eye_state=item["eye_state"], possible_drowsiness=item["drowsiness"], mar=item["mar"], yawning=item["yawning"], raised_hand=raised_hand))
            if item["drowsiness"]: db.add(Event(session_id=self.session_id, timestamp=timestamp, tracking_id=tracking_id, event_type="POSSIBLE_DROWSINESS", severity="WARNING", message=f"{tracking_id}: possible prolonged eye closure"))
            if item["yawning"]: db.add(Event(session_id=self.session_id, timestamp=timestamp, tracking_id=tracking_id, event_type="YAWNING", severity="INFO", message=f"{tracking_id}: sustained mouth opening detected"))
        return observations

    def _aggregate(self, db, timestamp: float, rows: list[dict]) -> None:
        count = len(rows); attention = sum(row["attention_score"] for row in rows) / count if count else 0
        drowsy = sum(row["drowsiness"] for row in rows); yawns = sum(self.yawning.counts.values()); looking_down = sum(row["attention_state"] == "LOOKING_DOWN" for row in rows) / count * 100 if count else 0
        raised_hands = sum(row["raised_hand"] for row in rows); looking_down_count = sum(row["attention_state"] == "LOOKING_DOWN" for row in rows); looking_away_count = sum(row["attention_state"] in {"LOOKING_LEFT", "LOOKING_RIGHT", "LOOKING_AWAY", "DISTRACTED"} for row in rows)
        orientation = sum(row["direction"] == "FRONT" for row in rows) / count * 100 if count else 0; eye_score = 100 - drowsy / count * 100 if count else 0
        engagement = float(calculate_engagement({"attention": attention, "orientation": orientation, "eye_state": eye_score, "activity": min(100, count / max(self.settings.expected_students, 1) * 100), "expression": 50})["engagement_score"])
        fatigue = float(calculate_fatigue(drowsy / count * 100 if count else 0, min(100, yawns * 5), looking_down, max(0, 70 - engagement))["fatigue_score"])
        self._snapshot(db, timestamp, count, attention, engagement, fatigue, drowsy, yawns, "REAL", raised_hands, looking_down_count, looking_away_count)
        conditions = [
            (looking_away_count >= max(3, count * .3), "HIGH_DISTRACTION", "WARNING", f"{looking_away_count} students were estimated as distracted or looking away."),
            (count and len(self.observed_ids) / max(self.settings.expected_students, 1) * 100 < 60, "LOW_ATTENDANCE", "WARNING", "Anonymous attendance estimate fell below 60%."),
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

    def _snapshot(self, db, timestamp, students, attention, engagement, fatigue, drowsy, yawns, mode, raised_hands=0, looking_down=0, looking_away=0):
        expected = max(1, self.settings.expected_students); seats = max(1, self.settings.total_seats); occupied = min(seats, students); distracted = round(students * max(0, 100 - attention) / 100)
        db.add(AnalyticsSnapshot(session_id=self.session_id, timestamp=round(timestamp, 2), student_count=students, visible_faces=students, attendance=round(len(self.observed_ids) / expected * 100, 2) if mode == "REAL" else round(students / expected * 100, 2), attention_score=round(attention, 2), engagement_score=round(engagement, 2), fatigue_score=round(fatigue, 2), drowsiness_count=drowsy, yawning_count=yawns, occupied_seats=occupied, empty_seats=max(0, seats - occupied), noise_level="UNKNOWN", distracted_students=distracted, raised_hands=raised_hands, looking_down_students=looking_down, looking_away_students=looking_away, details={"mode": mode, "identity": "anonymous"}))
        if engagement < 40: db.add(Alert(session_id=self.session_id, timestamp=timestamp, severity="WARNING", message="Estimated engagement fell below 40%."))

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
