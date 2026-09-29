"""Tests for the bounded /api/v1/dashboard/overview endpoint added for the
Phase 3A Overview dashboard redesign."""
from fastapi.testclient import TestClient

from backend.app import models
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app

Base.metadata.create_all(engine)


def test_empty_database_returns_zero_counts_not_errors():
    with TestClient(app) as client:
        body = client.get("/api/v1/dashboard/overview?data_source=ALL").json()
        assert body["session_counts"]["total"] >= 0
        assert body["reports_available"] >= 0
        assert isinstance(body["data_quality"]["tiers"], dict)


def test_session_counts_and_quality_tiers_reflect_real_data():
    with SessionLocal() as db:
        room = models.Classroom(name="Overview room", total_students=10, total_seats=10)
        db.add(room); db.flush()
        completed = models.Session(name="Overview completed", status="COMPLETED", classroom_id=room.id, analytics_mode="REAL", is_test=False)
        failed = models.Session(name="Overview failed", status="FAILED", classroom_id=room.id, analytics_mode="REAL", is_test=False)
        db.add_all([completed, failed]); db.flush()
        db.add_all([
            models.AnalyticsSnapshot(session_id=completed.id, timestamp=0, student_count=5),
            models.AnalyticsSnapshot(session_id=completed.id, timestamp=1, student_count=5),
        ])
        db.commit()
        room_id = room.id
    with TestClient(app) as client:
        body = client.get(f"/api/v1/dashboard/overview?classroom_id={room_id}&data_source=REAL").json()
        assert body["session_counts"]["completed"] >= 1
        assert body["session_counts"]["failed"] >= 1
        assert body["data_quality"]["tiers"]["HIGH"] >= 1  # both snapshots have student_count>0 -> coverage 1.0


def test_real_data_is_the_default_source():
    with SessionLocal() as db:
        test_session = models.Session(name="Overview test-only session", status="COMPLETED", is_test=True)
        db.add(test_session); db.commit()
    with TestClient(app) as client:
        body = client.get("/api/v1/dashboard/overview").json()
        names = [s["name"] for s in body["recent_sessions"]]
        assert "Overview test-only session" not in names


def test_test_data_source_filter_isolates_test_sessions():
    with SessionLocal() as db:
        test_session = models.Session(name="Overview isolated test session", status="COMPLETED", is_test=True)
        db.add(test_session); db.commit()
    with TestClient(app) as client:
        body = client.get("/api/v1/dashboard/overview?data_source=TEST").json()
        names = [s["name"] for s in body["recent_sessions"]]
        assert "Overview isolated test session" in names


def test_invalid_date_range_rejected():
    with TestClient(app) as client:
        r = client.get("/api/v1/dashboard/overview?start_date=2026-03-01&end_date=2026-01-01")
        assert r.status_code == 400
        assert r.json()["detail"]["error"]["code"] == "INVALID_DATE_RANGE"


def test_invalid_data_source_rejected():
    with TestClient(app) as client:
        r = client.get("/api/v1/dashboard/overview?data_source=NOT_REAL")
        assert r.status_code == 400
        assert r.json()["detail"]["error"]["code"] == "INVALID_DATA_SOURCE"


def test_classroom_filter_narrows_results():
    with SessionLocal() as db:
        room_a = models.Classroom(name="Overview filter A", total_students=5, total_seats=5)
        room_b = models.Classroom(name="Overview filter B", total_students=5, total_seats=5)
        db.add_all([room_a, room_b]); db.flush()
        session_a = models.Session(name="In room A", status="COMPLETED", classroom_id=room_a.id, analytics_mode="REAL", is_test=False)
        session_b = models.Session(name="In room B", status="COMPLETED", classroom_id=room_b.id, analytics_mode="REAL", is_test=False)
        db.add_all([session_a, session_b]); db.commit()
        room_a_id = room_a.id
    with TestClient(app) as client:
        body = client.get(f"/api/v1/dashboard/overview?classroom_id={room_a_id}").json()
        names = [s["name"] for s in body["recent_sessions"]]
        assert "In room A" in names
        assert "In room B" not in names


def test_reports_available_counts_distinct_sessions_not_report_rows():
    with SessionLocal() as db:
        room = models.Classroom(name="Overview report room", total_students=5, total_seats=5)
        db.add(room); db.flush()
        session = models.Session(name="Overview report session", status="COMPLETED", classroom_id=room.id, analytics_mode="REAL", is_test=False)
        db.add(session); db.flush()
        db.add_all([models.Report(session_id=session.id, format="csv", path="x.csv"), models.Report(session_id=session.id, format="pdf", path="x.pdf")])
        db.commit()
        room_id = room.id
    with TestClient(app) as client:
        body = client.get(f"/api/v1/dashboard/overview?classroom_id={room_id}").json()
        assert body["reports_available"] == 1


def test_auth_me_reports_dev_mode_and_display_name():
    with TestClient(app) as client:
        body = client.get("/api/v1/auth/me").json()
        assert body["auth_enabled"] is False
        assert body["display_name"]
