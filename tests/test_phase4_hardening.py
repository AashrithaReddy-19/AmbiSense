"""Phase 4 hardening: timezone-aware time handling, startup that never rewrites history, explicit confirmed cleanup with a
preview, and stale-job preview/recovery that never touches work a running worker owns."""
import re
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session as OrmSession

from backend.app import database, models
from backend.app.auth import create_token, decode_token, hash_password
from backend.app.config import Settings, get_settings
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.services import cleanup, jobs, retention
from backend.app.services.jobs import claim_retry, recover_interrupted_jobs, stale_job_report
from backend.app.services.semantic_search import search_sessions
from backend.app.timeutil import as_naive_utc, as_utc, utc_iso_z, utc_now, utc_now_naive

Base.metadata.create_all(engine)
settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "StrongPassword!123"


_FLAGGED_TEST_SESSIONS: list[int] = []


def _session(db, name, **kwargs):
    defaults = dict(status="COMPLETED", analytics_mode="REAL", is_test=False, source_type="VIDEO")
    defaults.update(kwargs)
    row = models.Session(name=name, **defaults)
    db.add(row)
    db.flush()
    if row.is_test:
        _FLAGGED_TEST_SESSIONS.append(row.id)
    return row


@pytest.fixture(autouse=True)
def _leave_no_flagged_sessions_behind():
    """The test database is shared by the whole run: sessions flagged as tests here must not be picked up by other tests' cleanup."""
    yield
    with SessionLocal() as db:
        if _FLAGGED_TEST_SESSIONS:
            db.execute(text("UPDATE sessions SET is_test = 0, archived = 0 WHERE id IN (%s)" % ",".join(str(i) for i in _FLAGGED_TEST_SESSIONS)))
            db.commit()
        _FLAGGED_TEST_SESSIONS.clear()


def _count(db, model, *where):
    return db.scalar(select(func.count(model.id)).where(*where)) or 0


@pytest.fixture
def token_auth():
    previous = (settings.auth_enabled, settings.auth_mode, settings.auth_secret_key)
    settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = True, "TOKEN", "phase4-test-secret-key-at-least-32-chars!"
    yield
    settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = previous


@pytest.fixture
def owned():
    """Simulate workers/connections that own sessions right now, and always release them."""
    runner = jobs.get_job_runner(settings)
    claimed_workers, claimed_live = [], []

    class Owner:
        def worker(self, session_id):
            runner._active_ids.add(session_id); claimed_workers.append(session_id)

        def live(self, session_id):
            jobs.live_connection_opened(session_id); claimed_live.append(session_id)

    yield Owner()
    for session_id in claimed_workers:
        runner._active_ids.discard(session_id)
    for session_id in claimed_live:
        jobs.live_connection_closed(session_id)


# --- Time handling ------------------------------------------------------------------------------------------------

def test_time_helpers_return_the_documented_kinds_of_utc():
    aware, naive = utc_now(), utc_now_naive()
    assert aware.tzinfo is not None and aware.utcoffset() == timedelta(0)
    assert naive.tzinfo is None
    assert abs((as_utc(naive) - aware).total_seconds()) < 5          # same instant, two representations
    assert as_utc(aware) is not None and as_utc(aware).tzinfo is not None
    assert as_naive_utc(aware).tzinfo is None and as_naive_utc(naive) == naive
    plus_five = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert as_naive_utc(plus_five) == datetime(2026, 1, 1, 6, 30) and as_utc(plus_five) == plus_five
    stamp = utc_iso_z()
    assert stamp.endswith("Z") and "+00:00" not in stamp and datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is not None
    assert utc_iso_z(datetime(2026, 3, 4, 5, 6, 7)) == "2026-03-04T05:06:07Z"


def test_aware_and_naive_values_compare_safely_only_after_normalisation():
    aware, naive = utc_now(), utc_now_naive()
    with pytest.raises(TypeError):
        _ = aware < naive                                          # the mix this project must never perform
    assert as_utc(naive) <= as_utc(aware) + timedelta(seconds=5)
    assert as_naive_utc(aware) <= as_naive_utc(naive) + timedelta(seconds=5)


def test_application_code_no_longer_calls_the_deprecated_utcnow():
    offenders = []
    for folder in ("backend", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name == "timeutil.py" or "__pycache__" in path.parts:
                continue
            if re.search(r"\.utcnow\s*\(|\.utcnow\b", path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_core_paths_emit_no_datetime_deprecation_warnings():
    """Row defaults, retention cutoffs, cleanup, stale-job reports, tokens and date search must all be warning-free."""
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*utcnow.*", category=DeprecationWarning)
        warnings.filterwarnings("error", message=".*utcfromtimestamp.*", category=DeprecationWarning)
        with SessionLocal() as db:
            row = _session(db, "Warning-free row", status="PROCESSING")     # created_at default fires here
            db.add(models.Notification(session_id=row.id, category="X", title="t", message="m", dedupe_key="warning-free"))
            db.commit()
            retention.retention_preview(db, settings)
            cleanup.preview_test_session_cleanup(db, settings)
            stale_job_report(db)
            search_sessions(db, "sessions from last week")
            user = models.User(email="warnfree@test", display_name="W", role="VIEWER", password_hash=hash_password(PASSWORD))
            db.add(user); db.flush()
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(settings, "auth_secret_key", "warning-free-secret-key-at-least-32-chars!")
                assert decode_token(create_token(user, settings), settings)["sub"] == str(user.id)
            db.rollback()


def test_row_defaults_are_naive_utc_close_to_now():
    with SessionLocal() as db:
        row = _session(db, "Default stamp")
        db.commit()
        stamped = db.get(models.Session, row.id).created_at
    assert stamped.tzinfo is None and abs((stamped - utc_now_naive()).total_seconds()) < 60


def test_retention_and_cleanup_cutoffs_are_naive_utc_whichever_kind_of_now_is_supplied():
    aware_now = utc_now()
    with SessionLocal() as db:
        old = _session(db, "Retention cutoff old", created_at=utc_now_naive() - timedelta(days=settings.retention_days + 5))
        fresh = _session(db, "Retention cutoff fresh", created_at=utc_now_naive() - timedelta(days=1))
        db.commit()
        for supplied in (aware_now, as_naive_utc(aware_now), None):
            preview = retention.retention_preview(db, settings, supplied)
            eligible = {item["id"] for item in preview["eligible_sessions"]}
            assert old.id in eligible and fresh.id not in eligible
            assert "+00:00" not in preview["cutoff"]
        expected = as_naive_utc(aware_now) - timedelta(days=settings.retention_days)
        assert datetime.fromisoformat(retention.retention_preview(db, settings, aware_now)["cutoff"]) == expected


def test_tokens_use_epoch_seconds_and_expire_on_schedule(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret_key", "expiry-test-secret-key-at-least-32-chars!")
    user = models.User(id=987654, email="expiry@test", display_name="E", role="VIEWER", password_hash="x", token_version=0)
    token = create_token(user, settings)
    payload = decode_token(token, settings)
    assert abs(payload["iat"] - time.time()) < 5 and payload["exp"] - payload["iat"] == settings.auth_access_token_expire_minutes * 60
    monkeypatch.setattr(time, "time", lambda: payload["exp"] + 1)
    with pytest.raises(Exception) as error:
        decode_token(token, settings)
    assert getattr(error.value, "status_code", None) == 401


def test_job_state_timestamps_are_naive_utc_and_recovery_stamps_end_time():
    with SessionLocal() as db:
        stale = _session(db, "Timestamp stale job", status="PROCESSING", started_at=utc_now_naive() - timedelta(minutes=30))
        db.commit(); stale_id = stale.id
        assert recover_interrupted_jobs(db, session_ids=[stale_id]) == [stale_id]
        row = db.get(models.Session, stale_id)
        assert row.status == "FAILED" and row.ended_at.tzinfo is None and abs((row.ended_at - utc_now_naive()).total_seconds()) < 60
        assert row.ended_at >= row.started_at


# --- Startup never rewrites history -------------------------------------------------------------------------------

def test_cleanup_defaults_are_off_and_documented():
    fresh = Settings(_env_file=None)
    assert fresh.scheduled_cleanup_enabled is False and fresh.test_session_cleanup_enabled is False
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SCHEDULED_CLEANUP_ENABLED=false" in example and "TEST_SESSION_CLEANUP_ENABLED=false" in example


def test_starting_the_app_does_not_archive_delete_flag_or_audit_anything(monkeypatch):
    monkeypatch.setattr(settings, "scheduled_cleanup_enabled", False)
    monkeypatch.setattr(settings, "test_session_cleanup_enabled", False)
    long_ago = utc_now_naive() - timedelta(days=60)
    with SessionLocal() as db:
        flagged = _session(db, "Startup flagged test", is_test=True, created_at=long_ago, data_source="TEST")
        lookalike = _session(db, "Priority 4 lookalike name", is_test=False, created_at=long_ago)   # name the old startup heuristic matched
        stuck = _session(db, "Startup stuck job", status="PROCESSING", created_at=long_ago)
        db.commit()
        ids = (flagged.id, lookalike.id, stuck.id)
        before = (_count(db, models.CleanupAudit), _count(db, models.AuditEntry), _count(db, models.Session))
    with TestClient(app):
        pass                                                         # runs the lifespan startup and shutdown
    with SessionLocal() as db:
        after = (_count(db, models.CleanupAudit), _count(db, models.AuditEntry), _count(db, models.Session))
        rows = {row.id: row for row in db.scalars(select(models.Session).where(models.Session.id.in_(ids)))}
    assert after == before
    assert rows[ids[0]].archived is False and rows[ids[1]].is_test is False and rows[ids[2]].status == "PROCESSING"


def test_even_when_scheduling_is_enabled_the_first_run_waits_one_interval(monkeypatch):
    monkeypatch.setattr(settings, "scheduled_cleanup_enabled", True)
    monkeypatch.setattr(settings, "test_session_cleanup_enabled", True)
    monkeypatch.setattr(settings, "test_session_cleanup_action", "ARCHIVE")
    monkeypatch.setattr(settings, "test_session_cleanup_age_hours", 1)
    with SessionLocal() as db:
        row = _session(db, "Scheduled waits", is_test=True, created_at=utc_now_naive() - timedelta(days=3))
        db.commit(); row_id = row.id
    with TestClient(app):
        with SessionLocal() as db:
            assert db.get(models.Session, row_id).archived is False   # nothing ran at startup


def test_legacy_backfill_of_test_flags_runs_once_when_the_column_is_added(tmp_path, monkeypatch):
    legacy_engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    Base.metadata.create_all(legacy_engine)
    with OrmSession(legacy_engine) as legacy_db:
        for name in ("Priority 3 legacy fixture", "Regular lecture"):
            _session(legacy_db, name)
        legacy_db.commit()
    with legacy_engine.begin() as connection:                      # simulate a database from before the column existed
        connection.execute(text("ALTER TABLE sessions DROP COLUMN is_test"))
    monkeypatch.setattr(database, "engine", legacy_engine)
    database.ensure_session_columns()
    with legacy_engine.connect() as connection:
        flags = dict(connection.execute(text("SELECT name, is_test FROM sessions")).fetchall())
    assert flags == {"Priority 3 legacy fixture": 1, "Regular lecture": 0}
    with legacy_engine.begin() as connection:                      # an operator un-flags it; a later start must respect that
        connection.execute(text("UPDATE sessions SET is_test=0"))
    database.ensure_session_columns()
    with legacy_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sessions WHERE is_test=1")).scalar() == 0
    legacy_engine.dispose()


# --- Manual cleanup: preview first, then explicit confirmation ----------------------------------------------------

def test_manual_test_cleanup_previews_then_requires_confirmation_and_audits(monkeypatch):
    monkeypatch.setattr(settings, "test_session_cleanup_enabled", False)     # the scheduled flag is off; manual must still work
    monkeypatch.setattr(settings, "test_session_cleanup_action", "ARCHIVE")
    monkeypatch.setattr(settings, "test_session_cleanup_age_hours", 1)
    with SessionLocal() as db:
        target = _session(db, "Manual cleanup target", is_test=True, created_at=utc_now_naive() - timedelta(days=2))
        running = _session(db, "Manual cleanup running", is_test=True, status="PROCESSING", created_at=utc_now_naive() - timedelta(days=2))
        real = _session(db, "Manual cleanup real", is_test=False, created_at=utc_now_naive() - timedelta(days=2))
        db.commit(); ids = (target.id, running.id, real.id)
        audits_before = _count(db, models.CleanupAudit)
    with TestClient(app) as client:
        preview = client.get("/api/v1/system/cleanup-test-sessions/preview")
        assert preview.status_code == 200 and preview.json()["status"] == "PREVIEW" and preview.json()["scheduled"] is False
        listed = {item["id"] for item in preview.json()["sessions"]}
        assert ids[0] in listed and ids[1] not in listed and ids[2] not in listed
        refused = client.post("/api/v1/system/cleanup-test-sessions")
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        with SessionLocal() as db:
            assert db.get(models.Session, ids[0]).archived is False and _count(db, models.CleanupAudit) == audits_before
        applied = client.post("/api/v1/system/cleanup-test-sessions?confirm=true")
        assert applied.status_code == 200 and applied.json()["status"] == "COMPLETED" and applied.json()["changed"] >= 1
        assert client.post("/api/v1/system/cleanup-test-sessions?confirm=true").json()["changed"] == 0   # idempotent
    with SessionLocal() as db:
        assert db.get(models.Session, ids[0]).archived is True
        assert db.get(models.Session, ids[1]).archived is False and db.get(models.Session, ids[2]).archived is False
        audit = db.scalar(select(models.CleanupAudit).where(models.CleanupAudit.session_id == ids[0], models.CleanupAudit.result == "CHANGED"))
        assert audit.details["trigger"] == "MANUAL"


def test_scheduled_path_honours_the_policy_flag_and_never_logs_a_no_op(monkeypatch):
    monkeypatch.setattr(settings, "test_session_cleanup_enabled", False)
    with SessionLocal() as db:
        before = _count(db, models.CleanupAudit)
        assert cleanup.cleanup_test_sessions(db, settings)["status"] == "DISABLED"
        monkeypatch.setattr(settings, "test_session_cleanup_enabled", True)
        monkeypatch.setattr(settings, "test_session_cleanup_age_hours", 24 * 3650)   # nothing is that old
        assert cleanup.cleanup_test_sessions(db, settings)["changed"] == 0
        assert _count(db, models.CleanupAudit) == before             # a scheduled no-op writes no audit noise


def test_transcript_retention_endpoint_also_needs_confirmation():
    with TestClient(app) as client:
        response = client.post("/api/v1/retention/transcripts/run")
        assert response.status_code == 400 and response.json()["error"]["code"] == "CONFIRMATION_REQUIRED"


# --- Stale-job preview and recovery -------------------------------------------------------------------------------

def _make_stale_world():
    old = utc_now_naive() - timedelta(hours=3)
    with SessionLocal() as db:
        rows = {
            "video": _session(db, "Stale video", status="PROCESSING", created_at=old, started_at=old),
            "decoding": _session(db, "Stale decoding", status="DECODING", created_at=old, started_at=old),
            "queued_old": _session(db, "Stale queued", status="QUEUED", created_at=old),
            "queued_fresh": _session(db, "Fresh queued", status="QUEUED"),
            "owned": _session(db, "Owned by a worker", status="PROCESSING", created_at=old, started_at=old),
            "live_dead": _session(db, "Dead live capture", status="PROCESSING", source_type="LIVE", created_at=old, started_at=old),
            "live_connected": _session(db, "Connected live capture", status="PROCESSING", source_type="LIVE", created_at=old, started_at=old),
            "stopped": _session(db, "Stopped live", status="STOPPED", source_type="LIVE"),
            "done": _session(db, "Finished", status="COMPLETED"),
        }
        db.commit()
        return {key: row.id for key, row in rows.items()}


def test_stale_report_lists_only_unowned_work_and_says_why(owned):
    ids = _make_stale_world()
    owned.worker(ids["owned"]); owned.live(ids["live_connected"])
    with SessionLocal() as db:
        before = {row.id: row.status for row in db.scalars(select(models.Session))}
        audit_before = _count(db, models.AuditEntry)
        report = stale_job_report(db)
        assert {row.id: row.status for row in db.scalars(select(models.Session))} == before and _count(db, models.AuditEntry) == audit_before   # read-only
    by_id = {item["id"]: item for item in report["items"]}
    assert {ids["video"], ids["decoding"], ids["queued_old"], ids["live_dead"]} <= set(by_id)
    assert not {ids["owned"], ids["live_connected"], ids["queued_fresh"], ids["stopped"], ids["done"]} & set(by_id)
    assert by_id[ids["video"]]["kind"] == "STALE_VIDEO_JOB" and by_id[ids["video"]]["recoverable"] is True and by_id[ids["video"]]["age_minutes"] >= 170
    assert by_id[ids["live_dead"]]["kind"] == "LIVE_CAPTURE_INTERRUPTED" and by_id[ids["live_dead"]]["recoverable"] is False
    assert "cannot continue" in report["explanation"] and "restart" in report["explanation"]
    assert report["runner"] == {"mode": "IN_PROCESS", "durable": False} and report["not_running"]["STOPPED"] >= 1
    assert report["recoverable"] == sum(1 for item in report["items"] if item["recoverable"])


def test_recovery_changes_only_stale_video_jobs_records_who_did_it_and_is_idempotent(owned):
    ids = _make_stale_world()
    owned.worker(ids["owned"]); owned.live(ids["live_connected"])
    with SessionLocal() as db:
        actor = models.User(email="recover-actor@test", display_name="Actor", role="ADMINISTRATOR", password_hash="x")
        db.add(actor); db.flush(); actor_id = actor.id
        first = recover_interrupted_jobs(db, actor_user_id=actor_id)
        assert {ids["video"], ids["decoding"], ids["queued_old"]} <= set(first)
        for untouched in ("queued_fresh", "owned", "live_dead", "live_connected", "stopped", "done"):
            assert ids[untouched] not in first, untouched
        statuses = {key: db.get(models.Session, value).status for key, value in ids.items()}
        assert statuses["owned"] == "PROCESSING" and statuses["live_dead"] == "PROCESSING" and statuses["live_connected"] == "PROCESSING"
        assert statuses["queued_fresh"] == "QUEUED" and statuses["stopped"] == "STOPPED" and statuses["done"] == "COMPLETED"
        assert statuses["video"] == "FAILED" and db.get(models.Session, ids["video"]).failure_code == "JOB_INTERRUPTED"
        entry = db.scalar(select(models.AuditEntry).where(models.AuditEntry.action == "JOB_RECOVERED", models.AuditEntry.resource_id == ids["video"]))
        assert entry.actor_user_id == actor_id and entry.details["previous_status"] == "PROCESSING"
        audits = _count(db, models.AuditEntry, models.AuditEntry.action == "JOB_RECOVERED")
        second = recover_interrupted_jobs(db, actor_user_id=actor_id)
        assert not set(second) & set(first)                                      # nothing recovered twice
        assert _count(db, models.AuditEntry, models.AuditEntry.action == "JOB_RECOVERED") == audits + len(second)


def test_recovery_can_be_limited_to_a_selection():
    ids = _make_stale_world()
    with SessionLocal() as db:
        recovered = recover_interrupted_jobs(db, session_ids=[ids["video"], ids["live_dead"], ids["done"]])
        assert recovered == [ids["video"]]                                       # live and finished sessions are never eligible
        assert db.get(models.Session, ids["decoding"]).status == "DECODING"


def test_retry_after_recovery_is_idempotent():
    ids = _make_stale_world()
    with SessionLocal() as db:
        recover_interrupted_jobs(db, session_ids=[ids["video"]])
        assert claim_retry(db, ids["video"]) is True and claim_retry(db, ids["video"]) is False
        row = db.get(models.Session, ids["video"])
        assert row.status == "QUEUED" and row.retry_count == 1 and row.failure_code is None


def test_stale_endpoints_preview_first_require_confirmation_and_honour_a_selection(owned):
    ids = _make_stale_world()
    owned.worker(ids["owned"])
    with TestClient(app) as client:
        preview = client.get("/api/v1/system/jobs/stale")
        assert preview.status_code == 200
        body = preview.json()
        assert ids["video"] in {item["id"] for item in body["items"]} and ids["owned"] not in {item["id"] for item in body["items"]}
        assert all("started_at" in item and "reason" in item for item in body["items"])
        with SessionLocal() as db:
            assert db.get(models.Session, ids["video"]).status == "PROCESSING"     # previewing changed nothing
        assert client.post("/api/v1/system/jobs/recover").status_code == 400
        result = client.post(f"/api/v1/system/jobs/recover?confirm=true&session_ids={ids['video']}&session_ids={ids['live_dead']}").json()
        assert result["recovered_session_ids"] == [ids["video"]] and result["requested_session_ids"] == [ids["video"], ids["live_dead"]]
        with SessionLocal() as db:
            assert db.get(models.Session, ids["decoding"]).status == "DECODING" and db.get(models.Session, ids["live_dead"]).status == "PROCESSING"
        assert client.post(f"/api/v1/system/jobs/recover?confirm=true&session_ids={ids['video']}").json()["count"] == 0
        health = client.get("/api/v1/system/diagnostics").json()["worker"]
        assert health["stale_jobs"] == len([item for item in client.get("/api/v1/system/jobs/stale").json()["items"] if item["recoverable"]])


def test_only_administrators_can_preview_or_recover_stale_jobs(token_auth):
    ids = _make_stale_world()
    with SessionLocal() as db:
        for email, role in (("stale-admin@test", "ADMINISTRATOR"), ("stale-instructor@test", "INSTRUCTOR")):
            db.add(models.User(email=email, display_name=email.split("@")[0], role=role, password_hash=hash_password(PASSWORD)))
        db.commit()
    with TestClient(app) as client:
        def headers(email):
            return {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]}
        admin, instructor = headers("stale-admin@test"), headers("stale-instructor@test")
        assert client.get("/api/v1/system/jobs/stale", headers=instructor).status_code == 403
        assert client.post("/api/v1/system/jobs/recover?confirm=true", headers=instructor).status_code == 403
        assert client.get("/api/v1/system/jobs/stale", headers=admin).status_code == 200
        with SessionLocal() as db:
            assert db.get(models.Session, ids["video"]).status == "PROCESSING"     # the refused calls changed nothing
        assert client.post(f"/api/v1/system/jobs/recover?confirm=true&session_ids={ids['video']}", headers=admin).json()["count"] == 1
        with SessionLocal() as db:
            entry = db.scalar(select(models.AuditEntry).where(models.AuditEntry.action == "JOB_RECOVERED", models.AuditEntry.resource_id == ids["video"]))
            admin_id = db.scalar(select(models.User.id).where(models.User.email == "stale-admin@test"))
            assert entry.actor_user_id == admin_id


def test_session_payloads_say_whether_a_session_is_stale_and_why(owned):
    ids = _make_stale_world()
    owned.worker(ids["owned"]); owned.live(ids["live_connected"])
    with TestClient(app) as client:
        def read(key):
            return client.get(f"/api/sessions/{ids[key]}").json()
        stale = read("video")
        assert stale["stale"] is True and stale["stale_kind"] == "STALE_VIDEO_JOB" and "No worker is processing" in stale["stale_reason"]
        assert read("live_dead")["stale_kind"] == "LIVE_CAPTURE_INTERRUPTED"
        for key in ("owned", "live_connected", "queued_fresh", "stopped", "done"):
            payload = read(key)
            assert payload["stale"] is False and payload["stale_kind"] is None and payload["stale_reason"] is None, key
        listed = client.get("/api/v1/sessions?q=Stale%20video&include_tests=true&page_size=100").json()
        by_id = {item["id"]: item for item in listed["items"]}
        assert by_id[ids["video"]]["stale"] is True and by_id[ids["video"]]["stale_kind"] == "STALE_VIDEO_JOB"
        finished = client.get("/api/v1/sessions?q=Finished&include_tests=true&page_size=100").json()
        assert any(item["id"] == ids["done"] and item["stale"] is False for item in finished["items"])
