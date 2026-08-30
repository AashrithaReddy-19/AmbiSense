from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.metrics import metric_envelope
from backend.app import models
from backend.app.services.priority4 import trend_buckets
from backend.app.main import app
from fastapi.testclient import TestClient
import cv2
import numpy as np


def test_metric_contract_preserves_zero_and_explains_missing_landmarks():
    zero = metric_envelope("occupancy", 0, valid_observations=1, eligible_observations=1, unit="count")
    assert zero["available"] is True
    assert zero["value"] == 0
    missing = metric_envelope("visual_orientation", None, valid_observations=0, eligible_observations=3)
    assert missing["available"] is False
    assert missing["value"] is None
    assert missing["reason"] == "facial_landmarks_unavailable"


def test_trends_use_coverage_weighting_and_keep_unavailable_as_gap():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        first=models.Session(name="A",status="COMPLETED",analytics_mode="REAL",created_at=datetime(2026,8,18),activity_context="LECTURE")
        second=models.Session(name="B",status="COMPLETED",analytics_mode="REAL",created_at=datetime(2026,8,19),activity_context="LECTURE")
        empty=models.Session(name="C",status="COMPLETED",analytics_mode="REAL",created_at=datetime(2026,8,26),activity_context="LECTURE")
        db.add_all([first,second,empty]);db.flush()
        db.add_all([
            models.AnalyticsSnapshot(session_id=first.id,timestamp=0,student_count=10,engagement_score=20),
            models.AnalyticsSnapshot(session_id=second.id,timestamp=0,student_count=10,engagement_score=80),
            models.AnalyticsSnapshot(session_id=second.id,timestamp=1,student_count=10,engagement_score=80),
        ]);db.commit()
        points=trend_buckets(db,[first,second,empty],"weekly",3,"observable_participation")
        available=next(point for point in points if point["value"] is not None)
        gap=next(point for point in points if point["value"] is None)
        assert available["value"] == 50.0
        assert available["contributing_sessions"] == 2
        assert gap["status"] == "INSUFFICIENT_EVIDENCE"
        assert gap["reason"]


def test_live_websocket_decodes_acknowledges_and_preserves_real_zero():
    client=TestClient(app)
    session=client.post("/api/sessions",json={"name":"acceptance live contract","source_type":"LIVE","is_test":True}).json()
    ok,jpeg=cv2.imencode(".jpg",np.zeros((240,320,3),dtype=np.uint8));assert ok
    with client.websocket_connect(f"/ws/live/{session['id']}") as socket:
        status=socket.receive_json();assert status["type"]=="status"
        socket.send_bytes(jpeg.tobytes())
        update=socket.receive_json()
        assert update["type"]=="live_metrics"
        assert update["transport"]["frames_received"]==1
        assert update["transport"]["frames_processed"]==1
        assert update["metrics"]["occupancy"]["available"] is True
        assert update["metrics"]["occupancy"]["value"]==0
        assert update["metrics"]["visual_orientation"]["available"] is False
        assert update["metrics"]["visual_orientation"]["reason"]=="no_detectable_person"
        socket.send_text("STOP")
