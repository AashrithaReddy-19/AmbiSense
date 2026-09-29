"""Backend tests for Phase 3C: Sessions date-range/coverage filters, Reports
search/activity_context/format filters, and search data-source separation."""
from datetime import datetime

from fastapi.testclient import TestClient

from backend.app import models
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app

Base.metadata.create_all(engine)


def _session(db, name, **kwargs):
    defaults = dict(status="COMPLETED", analytics_mode="REAL", is_test=False)
    defaults.update(kwargs)
    row = models.Session(name=name, **defaults)
    db.add(row)
    return row


# --- Sessions: start_date / end_date / minimum_coverage -----------------------

def test_sessions_start_date_filter():
    with SessionLocal() as db:
        old = _session(db, "Old filter session", created_at=datetime(2020, 1, 1))
        new = _session(db, "New filter session", created_at=datetime(2026, 6, 1))
        db.commit()
        old_id, new_id = old.id, new.id
    with TestClient(app) as client:
        body = client.get("/api/v1/sessions?start_date=2025-01-01&page_size=100").json()
        ids = {row["id"] for row in body["items"]}
        assert new_id in ids
        assert old_id not in ids


def test_sessions_end_date_filter():
    with SessionLocal() as db:
        old = _session(db, "End date old session", created_at=datetime(2020, 1, 1))
        new = _session(db, "End date new session", created_at=datetime(2026, 6, 1))
        db.commit()
        old_id, new_id = old.id, new.id
    with TestClient(app) as client:
        body = client.get("/api/v1/sessions?end_date=2021-01-01&page_size=100").json()
        ids = {row["id"] for row in body["items"]}
        assert old_id in ids
        assert new_id not in ids


def test_sessions_invalid_date_range_rejected():
    with TestClient(app) as client:
        r = client.get("/api/v1/sessions?start_date=2026-06-01&end_date=2026-01-01")
        assert r.status_code == 400
        assert r.json()["detail"]["error"]["code"] == "INVALID_DATE_RANGE"


def test_sessions_minimum_coverage_filter():
    with SessionLocal() as db:
        room = models.Classroom(name="Coverage filter room", total_students=10, total_seats=10)
        db.add(room); db.flush()
        high = _session(db, "High coverage session", classroom_id=room.id)
        low = _session(db, "Low coverage session", classroom_id=room.id)
        db.add_all([high, low]); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=high.id, timestamp=0, student_count=5))
        db.add(models.AnalyticsSnapshot(session_id=low.id, timestamp=0, student_count=0))
        db.add(models.AnalyticsSnapshot(session_id=low.id, timestamp=1, student_count=0))
        db.commit()
        high_id, low_id, room_id = high.id, low.id, room.id
    with TestClient(app) as client:
        body = client.get(f"/api/v1/sessions?classroom_id={room_id}&minimum_coverage=0.5&page_size=100").json()
        ids = {row["id"] for row in body["items"]}
        assert high_id in ids
        assert low_id not in ids


def test_sessions_invalid_coverage_rejected():
    with TestClient(app) as client:
        r = client.get("/api/v1/sessions?minimum_coverage=1.5")
        assert r.status_code == 400
        assert r.json()["detail"]["error"]["code"] == "INVALID_COVERAGE"


def test_sessions_filters_preserve_pagination():
    with SessionLocal() as db:
        room = models.Classroom(name="Pagination filter room", total_students=10, total_seats=10)
        db.add(room); db.flush()
        for i in range(5):
            db.add(_session(db, f"Pagination session {i}", classroom_id=room.id, created_at=datetime(2026, 6, 1)))
        db.commit()
        room_id = room.id
    with TestClient(app) as client:
        body = client.get(f"/api/v1/sessions?classroom_id={room_id}&start_date=2025-01-01&page=1&page_size=2").json()
        assert body["total"] >= 5
        assert len(body["items"]) == 2
        assert body["pages"] >= 3


# --- Reports: search / activity_context / format -------------------------------

def test_reports_search_filter():
    with SessionLocal() as db:
        db.add(_session(db, "Findable report session"))
        db.add(_session(db, "Other session name"))
        db.commit()
    with TestClient(app) as client:
        body = client.get("/api/v1/reports?q=Findable&data_source=ALL").json()
        assert any("Findable" in row["name"] for row in body["items"])
        assert all("Findable" in row["name"] for row in body["items"])


def test_reports_activity_context_filter():
    with SessionLocal() as db:
        db.add(_session(db, "Exam report session", activity_context="EXAMINATION"))
        db.add(_session(db, "Lecture report session", activity_context="LECTURE"))
        db.commit()
    with TestClient(app) as client:
        body = client.get("/api/v1/reports?activity_context=EXAMINATION&data_source=ALL").json()
        assert any(row["name"] == "Exam report session" for row in body["items"])
        assert not any(row["name"] == "Lecture report session" for row in body["items"])


def test_reports_format_filter_no_n_plus_1():
    with SessionLocal() as db:
        session = _session(db, "Formatted report session")
        db.add(session); db.flush()
        db.add(models.Report(session_id=session.id, format="pdf", path="x.pdf"))
        db.commit()
        session_id = session.id
    with TestClient(app) as client:
        body = client.get("/api/v1/reports?format=pdf&data_source=ALL").json()
        assert any(row["session_id"] == session_id for row in body["items"])
        matched = next(row for row in body["items"] if row["session_id"] == session_id)
        assert "pdf" in matched["available_formats"]


def test_reports_invalid_format_rejected():
    with TestClient(app) as client:
        r = client.get("/api/v1/reports?format=docx")
        assert r.status_code == 400


# --- Comparison: reliable event-frequency data ---------------------------------

def test_compare_includes_reliable_event_counts():
    from backend.app.services.priority4 import session_evidence
    with SessionLocal() as db:
        a = _session(db, "Event counts session A")
        b = _session(db, "Event counts session B")
        db.add_all([a, b]); db.flush()
        db.add(models.Event(session_id=a.id, timestamp=1, event_type="HAND_RAISED", severity="INFO", message="hand raised"))
        db.add(models.Event(session_id=a.id, timestamp=2, event_type="HAND_RAISED", severity="INFO", message="hand raised"))
        db.add(models.Event(session_id=a.id, timestamp=3, event_type="YAWNING", severity="INFO", message="yawn", review_state="EXCLUDED"))
        db.commit()
        evidence = session_evidence(db, a)
        assert evidence["event_counts"]["HAND_RAISED"] == 2
        assert "YAWNING" not in evidence["event_counts"]  # excluded events are not counted
        empty_evidence = session_evidence(db, b)
        assert empty_evidence["event_counts"] == {}


# --- Search: data-source separation and RBAC -----------------------------------

def test_search_defaults_to_real_and_excludes_test_sessions():
    with SessionLocal() as db:
        real = _session(db, "Search real session engagement")
        db.add(real); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=real.id, timestamp=0, engagement_score=20))
        test_session = _session(db, "Search test-flagged session engagement", is_test=True)
        db.add(test_session); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=test_session.id, timestamp=0, engagement_score=20))
        db.commit()
        real_id, test_id = real.id, test_session.id
    with TestClient(app) as client:
        body = client.post("/api/search", json={"query": "engagement below 50"}).json()
        ids = {m["session_id"] for m in body["matches"]}
        assert real_id in ids
        assert test_id not in ids
        assert body["data_source"] == "REAL"


def test_search_all_data_source_includes_test_sessions():
    with SessionLocal() as db:
        test_session = _session(db, "Search ALL test session engagement", is_test=True)
        db.add(test_session); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=test_session.id, timestamp=0, engagement_score=15))
        db.commit()
        test_id = test_session.id
    with TestClient(app) as client:
        body = client.post("/api/search", json={"query": "engagement below 50", "data_source": "ALL"}).json()
        ids = {m["session_id"] for m in body["matches"]}
        assert test_id in ids


def test_search_results_bounded():
    with TestClient(app) as client:
        body = client.post("/api/search", json={"query": "engagement below 100", "data_source": "ALL"}).json()
        assert len(body["matches"]) <= 100


def test_search_rbac_denies_unauthorized_session():
    from backend.app.auth import hash_password
    from backend.app.config import get_settings
    settings = get_settings()
    previous = (settings.auth_enabled, settings.auth_mode, settings.auth_secret_key)
    settings.auth_enabled = True; settings.auth_mode = "TOKEN"; settings.auth_secret_key = "search-rbac-test-secret-key-32-chars!"
    try:
        with SessionLocal() as db:
            owner = models.User(email="search-owner@test", display_name="Owner", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            other = models.User(email="search-other@test", display_name="Other", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            db.add_all([owner, other]); db.flush()
            room = models.Classroom(name="Search-only room", total_students=10, total_seats=10, owner_user_id=owner.id)
            db.add(room); db.flush()
            private_session = _session(db, "Search private engagement session", classroom_id=room.id)
            db.add(private_session); db.flush()
            db.add(models.AnalyticsSnapshot(session_id=private_session.id, timestamp=0, engagement_score=10))
            db.commit()
            other_email = other.email
        with TestClient(app) as client:
            token = client.post("/api/v1/auth/login", json={"email": other_email, "password": "StrongPassword!123"}).json()["access_token"]
            body = client.post("/api/search", json={"query": "engagement below 50", "data_source": "ALL"}, headers={"Authorization": f"Bearer {token}"}).json()
            assert all("private" not in m["session"].lower() for m in body["matches"])
    finally:
        settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = previous
