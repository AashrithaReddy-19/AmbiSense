"""Tests for the Phase 2 checkpoint: canonical trend/comparison contracts,
comparison validation, compatibility notices, and comparison CSV export."""
import csv
import io

from fastapi.testclient import TestClient

from backend.app.auth import hash_password
from backend.app.config import get_settings
from backend.app import models
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.metrics import metric_envelope
from backend.app.schemas import MetricAvailability

Base.metadata.create_all(engine)


def _seed_session(db, name, *, value=70, valid=8, total=10, methodology_version=None, status="COMPLETED", activity_context="LECTURE", classroom_id=None):
    session = models.Session(name=name, status=status, activity_context=activity_context, classroom_id=classroom_id)
    db.add(session); db.flush()
    envelope = metric_envelope("observable_participation", value, valid_observations=valid, eligible_observations=total)
    db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=0, student_count=total, engagement_score=value, details={"metrics": {"observable_participation": envelope}}))
    if methodology_version:
        db.add(models.EvidenceFusionResult(session_id=session.id, methodology_version=methodology_version, status="AVAILABLE", value=value, confidence=.7, coverage={}, components=[], limitations=[], weights={}))
    db.commit()
    return session.id


def test_comparison_with_two_valid_sessions():
    with SessionLocal() as db:
        a = _seed_session(db, "Compare A", value=60)
        b = _seed_session(db, "Compare B", value=80)
    with TestClient(app) as client:
        r = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b], "metrics": ["observable_participation"]})
        assert r.status_code == 200
        body = r.json()
        assert set(body["metric_results"]["observable_participation"]) == {str(a), str(b)}
        for entry in body["metric_results"]["observable_participation"].values():
            MetricAvailability(**entry)


def test_comparison_with_five_valid_sessions():
    with SessionLocal() as db:
        ids = [_seed_session(db, f"Five {i}", value=50 + i) for i in range(5)]
    with TestClient(app) as client:
        r = client.post("/api/v1/analytics/compare", json={"session_ids": ids, "metrics": ["observable_participation"]})
        assert r.status_code == 200
        assert len(r.json()["sessions"]) == 5


def test_one_session_rejected():
    with SessionLocal() as db:
        a = _seed_session(db, "Solo")
    with TestClient(app) as client:
        r = client.post("/api/v1/analytics/compare", json={"session_ids": [a], "metrics": ["observable_participation"]})
        assert r.status_code == 422  # pydantic min_length=2 on the request schema


def test_more_than_five_sessions_rejected():
    with SessionLocal() as db:
        ids = [_seed_session(db, f"Six {i}") for i in range(6)]
    with TestClient(app) as client:
        r = client.post("/api/v1/analytics/compare", json={"session_ids": ids, "metrics": ["observable_participation"]})
        assert r.status_code == 422  # pydantic max_length=5


def test_duplicate_ids_rejected():
    with SessionLocal() as db:
        a = _seed_session(db, "Dup A")
        b = _seed_session(db, "Dup B")
    with TestClient(app) as client:
        r = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b, a], "metrics": ["observable_participation"]})
        assert r.status_code == 422


def test_missing_session_rejected():
    with SessionLocal() as db:
        a = _seed_session(db, "Exists")
    with TestClient(app) as client:
        r = client.post("/api/v1/analytics/compare", json={"session_ids": [a, 999999], "metrics": ["observable_participation"]})
        assert r.status_code == 404
        assert r.json()["detail"]["error"]["code"] == "SESSION_NOT_FOUND"


def test_invalid_metric_rejected():
    with SessionLocal() as db:
        a = _seed_session(db, "Metric A"); b = _seed_session(db, "Metric B")
    with TestClient(app) as client:
        r = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b], "metrics": ["not_a_real_metric"]})
        assert r.status_code == 400
        assert r.json()["detail"]["error"]["code"] == "INVALID_METRIC"


def test_unauthorized_session_rejected():
    settings = get_settings()
    previous = (settings.auth_enabled, settings.auth_mode, settings.auth_secret_key)
    settings.auth_enabled = True; settings.auth_mode = "TOKEN"; settings.auth_secret_key = "comparison-test-secret-key-32-characters-long"
    try:
        with SessionLocal() as db:
            owner = models.User(email="compare-owner@test", display_name="Owner", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            other = models.User(email="compare-other@test", display_name="Other", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            db.add_all([owner, other]); db.flush()
            room = models.Classroom(name="Compare-only room", total_students=10, total_seats=10, owner_user_id=owner.id)
            db.add(room); db.flush()
            a = models.Session(name="Owner session A", status="COMPLETED", classroom_id=room.id)
            b = models.Session(name="Owner session B", status="COMPLETED", classroom_id=room.id)
            db.add_all([a, b]); db.commit()
            a_id, b_id, other_email = a.id, b.id, other.email
        with TestClient(app) as client:
            token = client.post("/api/v1/auth/login", json={"email": other_email, "password": "StrongPassword!123"}).json()["access_token"]
            r = client.post("/api/v1/analytics/compare", json={"session_ids": [a_id, b_id], "metrics": ["observable_participation"]}, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 403
            assert r.json()["detail"]["error"]["code"] == "SESSION_ACCESS_DENIED"
    finally:
        settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = previous


def test_incomplete_session_produces_warning():
    with SessionLocal() as db:
        a = _seed_session(db, "Complete one")
        b = _seed_session(db, "Still processing", status="PROCESSING")
    with TestClient(app) as client:
        body = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b], "metrics": ["observable_participation"]}).json()
        assert any(n["code"] == "SESSION_NOT_COMPLETED" for n in body["compatibility"]["notices"])


def test_genuine_zero_preserved_in_comparison():
    from sqlalchemy.orm.attributes import flag_modified
    with SessionLocal() as db:
        a = _seed_session(db, "Zero occupancy", value=0)
        # Give session `a`'s snapshot a genuine zero occupancy envelope too.
        # details is a plain JSON column, so in-place nested mutation needs
        # an explicit flag_modified() to be picked up by the ORM's flush.
        row = db.query(models.AnalyticsSnapshot).filter_by(session_id=a).one()
        row.details["metrics"]["occupancy"] = metric_envelope("occupancy", 0, valid_observations=1, eligible_observations=1, unit="count")
        flag_modified(row, "details"); db.add(row); db.commit()
        b = _seed_session(db, "Nonzero occupancy", value=50)
        row_b = db.query(models.AnalyticsSnapshot).filter_by(session_id=b).one()
        row_b.details["metrics"]["occupancy"] = metric_envelope("occupancy", 5, valid_observations=1, eligible_observations=1, unit="count")
        flag_modified(row_b, "details"); db.add(row_b); db.commit()
    with TestClient(app) as client:
        body = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b], "metrics": ["occupancy"]}).json()
        zero_entry = body["metric_results"]["occupancy"][str(a)]
        assert zero_entry["available"] is True
        assert zero_entry["value"] == 0


def test_unavailable_metric_remains_null_not_zero():
    with SessionLocal() as db:
        a = _seed_session(db, "Has participation")
        b = models.Session(name="No snapshots at all", status="COMPLETED")
        db.add(b); db.commit(); b_id = b.id
    with TestClient(app) as client:
        body = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b_id], "metrics": ["observable_participation"]}).json()
        empty_entry = body["metric_results"]["observable_participation"][str(b_id)]
        assert empty_entry["value"] is None
        assert empty_entry["available"] is False
        assert empty_entry["reason"] == "no_observations"


def test_legacy_session_without_evidence_reports_legacy_reason():
    with SessionLocal() as db:
        a = _seed_session(db, "Modern session")
        legacy = models.Session(name="Pre-contract session", status="COMPLETED")
        db.add(legacy); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=legacy.id, timestamp=0, student_count=10, engagement_score=55))  # no details.metrics
        db.commit(); legacy_id = legacy.id
    with TestClient(app) as client:
        body = client.post("/api/v1/analytics/compare", json={"session_ids": [a, legacy_id], "metrics": ["observable_participation"]}).json()
        entry = body["metric_results"]["observable_participation"][str(legacy_id)]
        assert entry["reason"] == "legacy_data_without_evidence"
        assert entry["value"] is None


def test_different_methodology_versions_produce_warning():
    with SessionLocal() as db:
        a = _seed_session(db, "Version one", methodology_version="1.0")
        b = _seed_session(db, "Version two", methodology_version="2.0")
    with TestClient(app) as client:
        body = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b], "metrics": ["observable_participation"]}).json()
        assert any(n["code"] == "DIFFERENT_METHODOLOGY_VERSIONS" for n in body["compatibility"]["notices"])
        assert body["compatibility"]["compatible"] is False


def test_low_coverage_spread_produces_warning():
    # LOW_COVERAGE_SPREAD compares session_evidence()'s coverage field,
    # which is the fraction of snapshots with any detected students -
    # distinct from a metric's own valid/total observation ratio.
    with SessionLocal() as db:
        high = _seed_session(db, "High coverage", value=70, valid=10, total=10)
        low = _seed_session(db, "Low coverage", value=70, valid=1, total=10)
        db.add(models.AnalyticsSnapshot(session_id=low, timestamp=1, student_count=0, engagement_score=None))
        db.add(models.AnalyticsSnapshot(session_id=low, timestamp=2, student_count=0, engagement_score=None))
        db.add(models.AnalyticsSnapshot(session_id=low, timestamp=3, student_count=0, engagement_score=None))
        db.commit()
    with TestClient(app) as client:
        body = client.post("/api/v1/analytics/compare", json={"session_ids": [high, low], "metrics": ["observable_participation"]}).json()
        assert any(n["code"] == "LOW_COVERAGE_SPREAD" for n in body["compatibility"]["notices"])


def test_comparison_csv_export_matches_api_values_and_escapes_formulas():
    with SessionLocal() as db:
        room = models.Classroom(name="=cmd|'/C calc'!A1", total_students=10, total_seats=10)
        db.add(room); db.flush()
        a = _seed_session(db, "CSV export A", value=42, classroom_id=room.id)
        b = _seed_session(db, "CSV export B", value=66, classroom_id=room.id)
    with TestClient(app) as client:
        api_body = client.post("/api/v1/analytics/compare", json={"session_ids": [a, b], "metrics": ["observable_participation"]}).json()
        r = client.get(f"/api/v1/analytics/compare/export?session_ids={a},{b}&metrics=observable_participation")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert rows[0]["classroom"].startswith("'"), "formula-like classroom name must be escaped with a leading apostrophe"
        for row in rows:
            api_entry = api_body["metric_results"][row["metric_name"]][row["session_id"]]
            expected_value = "" if api_entry["value"] is None else str(api_entry["value"])
            assert row["value"] == expected_value
            assert row["available"] == str(api_entry["available"])
            assert row["reason"] == (api_entry["reason"] or "")


def test_comparison_csv_requires_authorization():
    settings = get_settings()
    previous = (settings.auth_enabled, settings.auth_mode, settings.auth_secret_key)
    settings.auth_enabled = True; settings.auth_mode = "TOKEN"; settings.auth_secret_key = "csv-export-test-secret-key-32-characters!!"
    try:
        with SessionLocal() as db:
            owner = models.User(email="csv-owner@test", display_name="Owner", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            other = models.User(email="csv-other@test", display_name="Other", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            db.add_all([owner, other]); db.flush()
            room = models.Classroom(name="CSV-only room", total_students=10, total_seats=10, owner_user_id=owner.id)
            db.add(room); db.flush()
            a = models.Session(name="CSV A", status="COMPLETED", classroom_id=room.id)
            b = models.Session(name="CSV B", status="COMPLETED", classroom_id=room.id)
            db.add_all([a, b]); db.commit()
            a_id, b_id, other_email = a.id, b.id, other.email
        with TestClient(app) as client:
            token = client.post("/api/v1/auth/login", json={"email": other_email, "password": "StrongPassword!123"}).json()["access_token"]
            r = client.get(f"/api/v1/analytics/compare/export?session_ids={a_id},{b_id}", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 403
    finally:
        settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = previous


# --- Trend aggregation ---------------------------------------------------------

def test_trend_coverage_weighted_aggregation_and_all_unavailable_bucket():
    with SessionLocal() as db:
        room = models.Classroom(name="Trend room", total_students=20, total_seats=20)
        db.add(room); db.flush()
        high = models.Session(name="High weight", status="COMPLETED", classroom_id=room.id, activity_context="LECTURE")
        low = models.Session(name="Low weight", status="COMPLETED", classroom_id=room.id, activity_context="LECTURE")
        empty = models.Session(name="No evidence", status="COMPLETED", classroom_id=room.id, activity_context="LECTURE")
        db.add_all([high, low, empty]); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=high.id, timestamp=0, student_count=10, engagement_score=90, details={"metrics": {"observable_participation": metric_envelope("observable_participation", 90, valid_observations=10, eligible_observations=10)}}))
        db.add(models.AnalyticsSnapshot(session_id=low.id, timestamp=0, student_count=10, engagement_score=10, details={"metrics": {"observable_participation": metric_envelope("observable_participation", 10, valid_observations=1, eligible_observations=10)}}))
        db.commit()
        room_id, high_id, low_id, empty_id = room.id, high.id, low.id, empty.id
    with TestClient(app) as client:
        body = client.get(f"/api/v1/analytics/trends?classroom_id={room_id}&period=session&metric=observable_participation&data_source=ALL").json()
        points_by_session = {p["bucket"]: p for p in body["points"]}
        weighted = points_by_session[f"session-{high_id}"]
        assert weighted["result"]["available"] is True
        MetricAvailability(**weighted["result"])
        gap = points_by_session[f"session-{empty_id}"]
        assert gap["result"]["available"] is False
        assert gap["value"] is None
        MetricAvailability(**gap["result"])


def test_trend_test_data_source_filtering():
    with SessionLocal() as db:
        real = models.Session(name="Real trend session", status="COMPLETED", analytics_mode="REAL", is_test=False)
        test_session = models.Session(name="Test trend session", status="COMPLETED", is_test=True)
        db.add_all([real, test_session]); db.commit()
    with TestClient(app) as client:
        real_only = client.get("/api/v1/analytics/trends?period=session&data_source=REAL").json()
        test_only = client.get("/api/v1/analytics/trends?period=session&data_source=TEST").json()
        real_buckets = {p["bucket"] for p in real_only["points"]}
        test_buckets = {p["bucket"] for p in test_only["points"]}
        assert test_buckets.isdisjoint(real_buckets) or not (test_buckets & real_buckets)
