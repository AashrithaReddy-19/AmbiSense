"""Job runner (idempotent retry, atomic claim, duplicate-report prevention, recovery)
and retention/deletion (no orphans, managed-path-only file removal, audit trail)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from backend.app import models
from backend.app.config import get_settings
from backend.app.timeutil import utc_now_naive
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.services import jobs, retention
from backend.app.services.jobs import InProcessJobRunner, QueueJobRunner, claim_job, claim_retry, recover_interrupted_jobs, upsert_report

Base.metadata.create_all(engine)
settings = get_settings()


def _session(db, name, **kwargs):
    defaults = dict(status="COMPLETED", analytics_mode="REAL", is_test=False, source_type="VIDEO")
    defaults.update(kwargs)
    row = models.Session(name=name, **defaults)
    db.add(row)
    db.flush()
    return row


def _fk_violations() -> list:
    with engine.connect() as connection:
        return connection.execute(text("PRAGMA foreign_key_check")).fetchall()


# --- Job runner ---------------------------------------------------------------------

def test_claim_job_is_atomic_and_refuses_owned_or_finished_jobs():
    with SessionLocal() as db:
        queued = _session(db, "Claim queued", status="QUEUED")
        running = _session(db, "Claim running", status="PROCESSING")
        done = _session(db, "Claim done", status="COMPLETED")
        db.commit()
        assert claim_job(db, queued.id) is True
        assert claim_job(db, queued.id) is False  # second worker loses: now DECODING
        assert claim_job(db, running.id) is False
        assert claim_job(db, done.id) is False


def test_claim_retry_is_idempotent_only_one_caller_wins():
    with SessionLocal() as db:
        failed = _session(db, "Retry claim", status="FAILED", failure_code="X", error="boom", retry_count=0)
        db.commit()
        assert claim_retry(db, failed.id) is True
        assert claim_retry(db, failed.id) is False
        db.refresh(failed)
        assert failed.status == "QUEUED" and failed.retry_count == 1 and failed.error is None and failed.failure_code is None


def test_retry_endpoint_second_request_conflicts_without_double_queue(monkeypatch, tmp_path):
    video = settings.upload_dir / "retry-fixture.mp4"
    video.write_bytes(b"placeholder")
    dispatched = []
    monkeypatch.setattr(InProcessJobRunner, "dispatch", lambda self, *args, **kwargs: dispatched.append(args[0]))
    with SessionLocal() as db:
        failed = _session(db, "Retry endpoint", status="FAILED", job_id="retryjob0000000000000000000000001", video_path=str(video))
        db.commit()
        session_id = failed.id
    try:
        with TestClient(app) as client:
            first = client.post("/api/jobs/retryjob0000000000000000000000001/retry")
            second = client.post("/api/jobs/retryjob0000000000000000000000001/retry")
        assert first.status_code == 200 and first.json()["retry_count"] == 1
        assert second.status_code == 409 and second.json()["error"]["code"] == "JOB_NOT_RETRYABLE"
        assert dispatched == [session_id]
    finally:
        video.unlink(missing_ok=True)


def test_retry_requires_failed_status_and_a_retained_source():
    with SessionLocal() as db:
        _session(db, "Retry not failed", status="COMPLETED", job_id="retryjob0000000000000000000000002")
        _session(db, "Retry no source", status="FAILED", job_id="retryjob0000000000000000000000003", video_path="missing.mp4")
        db.commit()
    with TestClient(app) as client:
        assert client.post("/api/jobs/retryjob0000000000000000000000002/retry").json()["error"]["code"] == "JOB_NOT_RETRYABLE"
        assert client.post("/api/jobs/retryjob0000000000000000000000003/retry").json()["error"]["code"] == "SOURCE_VIDEO_UNAVAILABLE"
        assert client.post("/api/jobs/does-not-exist/retry").json()["error"]["code"] == "JOB_NOT_FOUND"


def test_upsert_report_never_duplicates_a_session_format_pair():
    with SessionLocal() as db:
        session = _session(db, "Upsert report")
        first = upsert_report(db, session.id, "pdf", "a.pdf")
        db.commit()
        second = upsert_report(db, session.id, "pdf", "b.pdf")
        db.commit()
        assert first.id == second.id
        assert db.scalar(select(func.count(models.Report.id)).where(models.Report.session_id == session.id)) == 1
        assert db.scalar(select(models.Report.path).where(models.Report.session_id == session.id)) == "b.pdf"


def test_report_downloads_create_exactly_one_row_per_format():
    with SessionLocal() as db:
        session = _session(db, "Download twice")
        db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=0, student_count=3))
        db.commit()
        session_id = session.id
    with TestClient(app) as client:
        for _ in range(2):
            for report_format in ("csv", "pdf", "metrics"):
                assert client.get(f"/api/sessions/{session_id}/report?format={report_format}").status_code == 200
    with SessionLocal() as db:
        formats = db.scalars(select(models.Report.format).where(models.Report.session_id == session_id)).all()
        assert sorted(formats) == ["csv", "metrics", "pdf"]


def test_recovery_marks_stale_video_jobs_failed_only_on_explicit_confirmed_request():
    with SessionLocal() as db:
        stale = _session(db, "Stale job", status="PROCESSING", source_type="VIDEO")
        live = _session(db, "Live untouched", status="PROCESSING", source_type="LIVE")
        db.commit()
        stale_id, live_id = stale.id, live.id
    with TestClient(app) as client:
        assert client.post("/api/v1/system/jobs/recover").status_code == 400  # confirmation required
        with SessionLocal() as db:
            assert db.get(models.Session, stale_id).status == "PROCESSING"
        result = client.post("/api/v1/system/jobs/recover?confirm=true").json()
    assert stale_id in result["recovered_session_ids"] and live_id not in result["recovered_session_ids"]
    with SessionLocal() as db:
        row = db.get(models.Session, stale_id)
        assert row.status == "FAILED" and row.failure_code == "JOB_INTERRUPTED"
        assert db.get(models.Session, live_id).status == "PROCESSING"
        assert db.scalar(select(models.AuditEntry.id).where(models.AuditEntry.action == "JOB_RECOVERED", models.AuditEntry.resource_id == stale_id))


def test_in_process_runner_health_and_queue_runner_contract():
    with SessionLocal() as db:
        health = InProcessJobRunner().health(db)
        assert health["mode"] == "IN_PROCESS" and health["durable"] is False and "stale_jobs" in health
        assert QueueJobRunner().health(db)["healthy"] is False
    with pytest.raises(NotImplementedError):
        QueueJobRunner().dispatch(1, "x", settings)


def test_get_job_runner_is_a_singleton_in_process_runner():
    assert jobs.get_job_runner(settings) is jobs.get_job_runner(settings)
    assert jobs.get_job_runner(settings).mode == "IN_PROCESS"


# --- Deletion and retention ----------------------------------------------------------

def _full_session(db, name, *, video: bool = True):
    session = _session(db, name)
    files = {}
    if video:
        files["video"] = settings.upload_dir / f"{name.replace(' ', '_')}.mp4"
        files["video"].write_bytes(b"video")
        session.video_path = str(files["video"])
    files["annotated"] = settings.report_dir / f"annotated_{session.id}.mp4"
    files["annotated"].write_bytes(b"annotated")
    session.annotated_video_path = str(files["annotated"])
    for report_format, suffix in (("pdf", "pdf"), ("csv", "csv")):
        path = settings.report_dir / f"session_{session.id}.{suffix}"
        path.write_bytes(b"report")
        files[report_format] = path
        db.add(models.Report(session_id=session.id, format=report_format, path=str(path)))
    audio = settings.report_dir / f"audio_{session.id}.wav"
    audio.write_bytes(b"audio")
    files["audio"] = audio
    db.add(models.AudioAnalysis(session_id=session.id, status="AVAILABLE", audio_path=str(audio)))
    db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=0, student_count=2))
    db.add(models.Event(session_id=session.id, timestamp=1, event_type="HAND_RAISED", severity="INFO", message="hand"))
    db.add(models.Notification(user_id=None, session_id=session.id, category="POOR_CAMERA", title="t", message="m", dedupe_key=f"k-{session.id}"))
    db.add(models.CollaborationNote(scope_type="SESSION", scope_id=session.id, body="note"))
    segment = models.TranscriptSegment(id=f"seg-{session.id}", session_id=session.id, start_seconds=0, end_seconds=1, original_text="hello", confidence=.9, language="en", speaker_role="UNKNOWN", provider="p", generated=True)
    db.add(segment)
    db.flush()
    db.add(models.TranscriptCorrection(segment_id=segment.id, previous_text="hello", corrected_text="hi"))
    db.commit()
    return session.id, files


def test_delete_requires_confirmation_then_removes_rows_files_and_audits():
    with SessionLocal() as db:
        session_id, files = _full_session(db, "Delete everything")
    with TestClient(app) as client:
        refused = client.delete(f"/api/sessions/{session_id}")
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        assert all(path.exists() for path in files.values())
        result = client.delete(f"/api/sessions/{session_id}?confirm=true").json()
    assert result["status"] == "deleted" and result["artifacts"]["failed"] == 0
    assert not any(path.exists() for path in files.values())
    with SessionLocal() as db:
        assert db.get(models.Session, session_id) is None
        for model in retention.SESSION_CHILD_MODELS:
            assert db.scalar(select(func.count()).select_from(model).where(model.session_id == session_id)) == 0, model.__tablename__
        assert db.scalar(select(func.count(models.CollaborationNote.id)).where(models.CollaborationNote.scope_type == "SESSION", models.CollaborationNote.scope_id == session_id)) == 0
        assert db.scalar(select(func.count(models.TranscriptCorrection.id)).where(models.TranscriptCorrection.segment_id == f"seg-{session_id}")) == 0
        audit = db.scalar(select(models.AuditEntry).where(models.AuditEntry.action == "SESSION_DELETED", models.AuditEntry.resource_id == session_id))
        assert audit is not None and audit.details["rows_deleted"]["notifications"] == 1
    assert _fk_violations() == []  # no dangling foreign keys after deletion


def test_delete_never_removes_files_outside_managed_directories(tmp_path):
    outside = tmp_path / "precious.mp4"
    outside.write_bytes(b"keep me")
    with SessionLocal() as db:
        session = _session(db, "Outside path delete", video_path=str(outside))
        db.commit()
        session_id = session.id
    with TestClient(app) as client:
        result = client.delete(f"/api/sessions/{session_id}?confirm=true").json()
    assert outside.exists()
    assert result["artifacts"]["skipped_unmanaged"] == 1


def test_active_sessions_cannot_be_deleted_or_have_artifacts_removed():
    with SessionLocal() as db:
        session = _session(db, "Active protected", status="PROCESSING")
        db.commit()
        session_id = session.id
    with TestClient(app) as client:
        assert client.delete(f"/api/sessions/{session_id}?confirm=true").json()["error"]["code"] == "SESSION_ACTIVE"
        assert client.delete(f"/api/v1/sessions/{session_id}/artifacts?kinds=reports&confirm=true").json()["error"]["code"] == "SESSION_ACTIVE"


def test_artifact_listing_only_shows_files_that_exist():
    with SessionLocal() as db:
        session_id, files = _full_session(db, "Artifact listing")
    files["annotated"].unlink()
    with TestClient(app) as client:
        kinds = {item["kind"] for item in client.get(f"/api/v1/sessions/{session_id}/artifacts").json()["artifacts"]}
    assert {"source_video", "report_pdf", "report_csv"} <= kinds
    assert "annotated_video" not in kinds and "report_metrics" not in kinds


def test_artifact_deletion_keeps_evidence_and_is_audited():
    with SessionLocal() as db:
        session_id, files = _full_session(db, "Artifact deletion")
    with TestClient(app) as client:
        assert client.delete(f"/api/v1/sessions/{session_id}/artifacts?kinds=nonsense&confirm=true").json()["error"]["code"] == "INVALID_ARTIFACT_KIND"
        assert client.delete(f"/api/v1/sessions/{session_id}/artifacts?kinds=reports").json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        result = client.delete(f"/api/v1/sessions/{session_id}/artifacts?kinds=reports,source_video&confirm=true").json()
    assert result["kinds"] == ["reports", "source_video"]
    assert not files["pdf"].exists() and not files["csv"].exists() and not files["video"].exists()
    assert files["annotated"].exists() and files["audio"].exists()
    with SessionLocal() as db:
        session = db.get(models.Session, session_id)
        assert session is not None and session.video_path is None and session.annotated_video_path
        assert db.scalar(select(func.count(models.Report.id)).where(models.Report.session_id == session_id)) == 0
        assert db.scalar(select(func.count(models.AnalyticsSnapshot.id)).where(models.AnalyticsSnapshot.session_id == session_id)) == 1
        assert db.scalar(select(models.AuditEntry.id).where(models.AuditEntry.action == "ARTIFACTS_DELETED", models.AuditEntry.resource_id == session_id))


def test_test_session_cleanup_delete_action_leaves_no_orphans(monkeypatch):
    from datetime import datetime, timedelta

    from backend.app.services.cleanup import cleanup_test_sessions

    with SessionLocal() as db:
        session_id, files = _full_session(db, "Cleanup orphan check")
        db.get(models.Session, session_id).is_test = True
        db.get(models.Session, session_id).created_at = utc_now_naive() - timedelta(days=3)
        db.commit()
        monkeypatch.setattr(settings, "test_session_cleanup_enabled", True)
        monkeypatch.setattr(settings, "test_session_cleanup_action", "DELETE")
        monkeypatch.setattr(settings, "test_session_cleanup_age_hours", 1)
        cleanup_test_sessions(db, settings)
        assert db.get(models.Session, session_id) is None
    assert not any(path.exists() for path in files.values())
    assert _fk_violations() == []


def test_retention_policy_previews_then_archives_only_when_confirmed(monkeypatch):
    from datetime import datetime, timedelta

    monkeypatch.setattr(settings, "retention_days", 30)
    with SessionLocal() as db:
        old = _session(db, "Retention old", created_at=utc_now_naive() - timedelta(days=90))
        fresh = _session(db, "Retention fresh")
        active = _session(db, "Retention active old", status="PROCESSING", created_at=utc_now_naive() - timedelta(days=90))
        db.commit()
        old_id, fresh_id, active_id = old.id, fresh.id, active.id
    with TestClient(app) as client:
        preview = client.get("/api/v1/retention/policy").json()
        eligible = {item["id"] for item in preview["eligible_sessions"]}
        assert old_id in eligible and fresh_id not in eligible and active_id not in eligible
        assert client.post("/api/v1/retention/sessions/run").status_code == 400
        result = client.post("/api/v1/retention/sessions/run?confirm=true").json()
    assert old_id in result["session_ids"]
    with SessionLocal() as db:
        assert db.get(models.Session, old_id).archived is True
        assert db.get(models.Session, fresh_id).archived is False
        assert db.get(models.Session, active_id).archived is False
        assert db.scalar(select(models.AuditEntry.id).where(models.AuditEntry.action == "RETENTION_ARCHIVE_RUN"))
