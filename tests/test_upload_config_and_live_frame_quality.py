"""Tests for the Phase 3B backend additions: classroom/activity_context/
course_id on video upload, and frame_quality in the live WebSocket metrics."""
import io
import os
import tempfile

import cv2
import numpy as np
from fastapi.testclient import TestClient

from backend.app import models
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.schemas import MetricAvailability

Base.metadata.create_all(engine)


def _tiny_video_bytes() -> bytes:
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (32, 32))
        for _ in range(5):
            writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
        writer.release()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


def test_upload_assigns_classroom_and_activity_context():
    with SessionLocal() as db:
        room = models.Classroom(name="Upload config room", total_students=10, total_seats=10)
        db.add(room); db.commit()
        room_id = room.id
    with TestClient(app) as client:
        video = _tiny_video_bytes()
        r = client.post(
            "/api/uploads",
            files={"file": ("clip.mp4", io.BytesIO(video), "video/mp4")},
            data={"name": "Configured upload", "classroom_id": str(room_id), "activity_context": "GROUP_DISCUSSION"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["classroom_id"] == room_id
        assert body["activity_context"] == "GROUP_DISCUSSION"


def test_upload_rejects_unknown_classroom():
    with TestClient(app) as client:
        video = _tiny_video_bytes()
        r = client.post(
            "/api/uploads",
            files={"file": ("clip.mp4", io.BytesIO(video), "video/mp4")},
            data={"name": "Bad classroom", "classroom_id": "999999"},
        )
        assert r.status_code == 404


def test_upload_rejects_empty_file():
    with TestClient(app) as client:
        r = client.post("/api/uploads", files={"file": ("empty.mp4", io.BytesIO(b""), "video/mp4")}, data={"name": "Empty"})
        assert r.status_code in (413, 415, 422)


def test_session_analytics_includes_canonical_metric_results():
    with SessionLocal() as db:
        room = models.Classroom(name="Session summary room", total_students=10, total_seats=10)
        db.add(room); db.flush()
        session = models.Session(name="Session summary metrics", status="COMPLETED", classroom_id=room.id)
        db.add(session); db.flush()
        from backend.app.metrics import metric_envelope
        db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=0, student_count=8, engagement_score=70, details={"metrics": {"observable_participation": metric_envelope("observable_participation", 70, valid_observations=8, eligible_observations=8)}}))
        db.commit(); session_id = session.id
    with TestClient(app) as client:
        body = client.get(f"/api/sessions/{session_id}/analytics").json()
        assert "metric_results" in body
        MetricAvailability(**body["metric_results"]["observable_participation"])
        MetricAvailability(**body["metric_results"]["frame_quality"])
        assert body["metric_results"]["observable_participation"]["available"] is True
        assert body["metric_results"]["observable_participation"]["value"] == 70


def test_session_analytics_metric_results_for_session_without_snapshots():
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"name": "no snapshots yet", "is_test": True}).json()
        body = client.get(f"/api/sessions/{session['id']}/analytics").json()
        assert body["snapshots"] == 0
        assert "metric_results" in body
        for contract in body["metric_results"].values():
            MetricAvailability(**contract)
            assert contract["value"] is None


def test_live_websocket_includes_canonical_frame_quality():
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"name": "live frame quality", "source_type": "LIVE", "is_test": True}).json()
        ok, jpeg = cv2.imencode(".jpg", np.zeros((240, 320, 3), dtype=np.uint8))
        assert ok
        with client.websocket_connect(f"/ws/live/{session['id']}") as socket:
            socket.receive_json()
            socket.send_bytes(jpeg.tobytes())
            update = socket.receive_json()
            assert "frame_quality" in update["metrics"]
            MetricAvailability(**update["metrics"]["frame_quality"])
            socket.send_text("STOP")
