"""Session-metadata search: explicit allowlisted filters, truthful applied/not-applied
lists, data-source separation, RBAC and bounds."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import models
from backend.app.auth import hash_password
from backend.app.config import get_settings
from backend.app.timeutil import utc_now_naive
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.services.semantic_search import _date_range, is_session_query

Base.metadata.create_all(engine)


def _session(db, name, **kwargs):
    defaults = dict(status="COMPLETED", analytics_mode="REAL", is_test=False, activity_context="LECTURE")
    defaults.update(kwargs)
    row = models.Session(name=name, **defaults)
    db.add(row)
    db.flush()
    return row


def _snapshots(db, session, present, absent):
    for index in range(present):
        db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=index, student_count=3))
    for index in range(absent):
        db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=100 + index, student_count=0))


def _search(client, query, source="ALL", headers=None):
    response = client.post("/api/search", json={"query": query, "data_source": source}, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


def _names(body):
    return {match["session"] for match in body["matches"]}


def test_query_classification():
    assert is_session_query("find failed processing jobs")
    assert is_session_query("show reports from classroom a")
    assert not is_session_query("show when more than 10 students were distracted")
    assert not is_session_query("engagement below 50")


def test_date_ranges_are_explicit_and_documented():
    now = datetime(2026, 9, 30, 15, 0)  # a Wednesday
    monday = datetime(2026, 9, 28)
    assert _date_range("from last week", now)[:2] == (monday - timedelta(days=7), monday)
    assert _date_range("this week", now)[:2] == (monday, now)
    assert _date_range("yesterday", now)[:2] == (datetime(2026, 9, 29), datetime(2026, 9, 30))
    assert _date_range("in the last 3 days", now)[:2] == (now - timedelta(days=3), now)
    assert _date_range("last month", now)[:2] == (datetime(2026, 8, 1), datetime(2026, 9, 1))
    assert _date_range("no date words", now) == (None, None, None)
    assert "previous calendar week" in _date_range("last week", now)[2]


def test_failed_processing_jobs_returns_only_failed_sessions():
    with SessionLocal() as db:
        _session(db, "Search failed one", status="FAILED", failure_code="X")
        _session(db, "Search still processing", status="PROCESSING")
        _session(db, "Search done fine", status="COMPLETED")
        db.commit()
    with TestClient(app) as client:
        body = _search(client, "Find failed processing jobs.")
    assert "Search failed one" in _names(body)
    assert "Search still processing" not in _names(body) and "Search done fine" not in _names(body)
    assert body["match_kind"] == "EXPLICIT_FILTERS"
    assert [item["name"] for item in body["applied_filters"] if item["name"] == "status"] == ["status"]
    assert all(match["status"] == "FAILED" for match in body["matches"])


def test_completed_lecture_sessions_from_last_week():
    monday = utc_now_naive().replace(hour=0, minute=0, second=0, microsecond=0)
    monday -= timedelta(days=monday.weekday())
    with SessionLocal() as db:
        _session(db, "Search last-week lecture", created_at=monday - timedelta(days=4))
        _session(db, "Search last-week exam", created_at=monday - timedelta(days=4), activity_context="EXAMINATION")
        _session(db, "Search last-week failed lecture", created_at=monday - timedelta(days=4), status="FAILED")
        _session(db, "Search this-week lecture", created_at=utc_now_naive())
        _session(db, "Search old lecture", created_at=monday - timedelta(days=30))
        db.commit()
    with TestClient(app) as client:
        body = _search(client, "Show completed lecture sessions from last week.")
    assert "Search last-week lecture" in _names(body)
    assert not ({"Search last-week exam", "Search last-week failed lecture", "Search this-week lecture", "Search old lecture"} & _names(body))
    applied = {item["name"]: item["description"] for item in body["applied_filters"]}
    assert {"status", "activity_context", "date_range", "data_source", "access"} <= set(applied)
    assert "previous calendar week" in applied["date_range"]
    assert body["interpreted_filter"]["activity_context"] == "LECTURE"


def test_reports_from_a_named_classroom_requires_reports_and_that_classroom():
    with SessionLocal() as db:
        room_a = models.Classroom(name="Classroom A", total_students=10, total_seats=10)
        room_b = models.Classroom(name="Classroom B", total_students=10, total_seats=10)
        db.add_all([room_a, room_b]); db.flush()
        with_report = _session(db, "Search A with report", classroom_id=room_a.id)
        _session(db, "Search A without report", classroom_id=room_a.id)
        other_report = _session(db, "Search B with report", classroom_id=room_b.id)
        db.add_all([models.Report(session_id=with_report.id, format="pdf", path="a.pdf"), models.Report(session_id=other_report.id, format="pdf", path="b.pdf")])
        db.commit()
    with TestClient(app) as client:
        body = _search(client, "Show reports from Classroom A.")
    assert "Search A with report" in _names(body)
    assert not ({"Search A without report", "Search B with report"} & _names(body))
    assert any(item["name"] == "has_report" for item in body["applied_filters"])
    assert next(m for m in body["matches"] if m["session"] == "Search A with report")["has_report"] is True


def test_unknown_classroom_returns_nothing_and_says_so():
    with TestClient(app) as client:
        body = _search(client, "Show reports from Classroom Zzyzx.")
    assert body["matches"] == []
    assert any("no classroom has that name" in item["description"] for item in body["applied_filters"])


def test_low_evidence_coverage_includes_sparse_and_empty_sessions_but_not_well_covered_ones():
    with SessionLocal() as db:
        sparse = _session(db, "Search sparse coverage")
        _snapshots(db, sparse, present=1, absent=9)
        _session(db, "Search no evidence at all")
        well = _session(db, "Search well covered")
        _snapshots(db, well, present=9, absent=1)
        db.commit()
    with TestClient(app) as client:
        body = _search(client, "Find sessions with low evidence coverage.")
        names = _names(body)
        assert {"Search sparse coverage", "Search no evidence at all"} <= names and "Search well covered" not in names
        by_name = {m["session"]: m for m in body["matches"]}
        assert by_name["Search sparse coverage"]["coverage"] == pytest.approx(0.1) and by_name["Search no evidence at all"]["coverage"] is None
        high = _names(_search(client, "Show sessions with high coverage"))
        assert "Search well covered" in high and "Search sparse coverage" not in high
        numeric = _names(_search(client, "sessions with coverage below 20%"))
        assert "Search sparse coverage" in numeric and "Search well covered" not in numeric


def test_unrecognised_session_query_reports_what_was_not_applied():
    with TestClient(app) as client:
        body = _search(client, "Show me my sessions please")
    assert body["not_applied"] and body["not_applied"][0]["name"] == "query"


def test_metric_searches_never_claim_a_date_filter_they_did_not_apply():
    with TestClient(app) as client:
        body = _search(client, "engagement below 50 from last week")
    names = {item["name"] for item in body["applied_filters"]}
    assert "metric" in names and "threshold" in names and "date_range" not in names
    assert [item["name"] for item in body["not_applied"]] == ["date_range"]
    assert body["match_kind"] == "KEYWORD_METRIC"


def test_data_source_separation_and_default_real_for_session_search():
    with SessionLocal() as db:
        _session(db, "Search src real failed", status="FAILED")
        _session(db, "Search src test failed", status="FAILED", is_test=True)
        _session(db, "Search src demo failed", status="FAILED", analytics_mode="DEMO")
        db.commit()
    with TestClient(app) as client:
        real = _names(_search(client, "failed jobs", source="REAL"))
        test = _names(_search(client, "failed jobs", source="TEST"))
        demo = _names(_search(client, "failed jobs", source="DEMO"))
        everything = _names(_search(client, "failed jobs", source="ALL"))
        default = client.post("/api/search", json={"query": "failed jobs"}).json()
    assert "Search src real failed" in real and not ({"Search src test failed", "Search src demo failed"} & real)
    assert "Search src test failed" in test and "Search src real failed" not in test
    assert "Search src demo failed" in demo and "Search src real failed" not in demo
    assert {"Search src real failed", "Search src test failed", "Search src demo failed"} <= everything
    assert default["data_source"] == "REAL" and "Search src test failed" not in {m["session"] for m in default["matches"]}


def test_session_search_is_bounded_and_reports_truncation():
    with SessionLocal() as db:
        for index in range(105):
            _session(db, f"Search bulk {index}", status="STOPPED")
        db.commit()
    with TestClient(app) as client:
        body = _search(client, "stopped sessions")
    assert len(body["matches"]) <= 100 and body["bounded"] == {"limit": 100, "returned": len(body["matches"]), "truncated": True}


def test_session_search_never_returns_sessions_the_user_cannot_access():
    # Resolve settings at call time: an earlier migration test clears the get_settings() cache, which yields a new instance.
    settings = get_settings()
    previous = (settings.auth_enabled, settings.auth_mode, settings.auth_secret_key)
    settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = True, "TOKEN", "search-sessions-secret-key-at-least-32!"
    try:
        with SessionLocal() as db:
            owner = models.User(email="ss-owner@test", display_name="Owner", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            other = models.User(email="ss-other@test", display_name="Other", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            db.add_all([owner, other]); db.flush()
            room = models.Classroom(name="Private search room", total_students=5, total_seats=5, owner_user_id=owner.id)
            db.add(room); db.flush()
            _session(db, "Search private failed", status="FAILED", classroom_id=room.id)
            _session(db, "Search public failed", status="FAILED")
            db.commit()
        with TestClient(app) as client:
            def headers(email):
                token = client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPassword!123"}).json()["access_token"]
                return {"Authorization": f"Bearer {token}"}
            as_other = _names(_search(client, "failed jobs", headers=headers("ss-other@test")))
            as_owner = _names(_search(client, "failed jobs", headers=headers("ss-owner@test")))
        assert "Search public failed" in as_other and "Search private failed" not in as_other
        assert {"Search public failed", "Search private failed"} <= as_owner
    finally:
        settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = previous


def test_archived_sessions_are_not_searched():
    with SessionLocal() as db:
        _session(db, "Search archived failed", status="FAILED", archived=True)
        db.commit()
    with TestClient(app) as client:
        assert "Search archived failed" not in _names(_search(client, "failed jobs"))
