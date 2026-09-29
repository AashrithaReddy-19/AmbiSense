"""Session deletion, artifact deletion and retention helpers.

Database rows are removed in one transaction first; files are removed only
after the commit succeeds and only when they resolve inside the configured
upload/report/reference directories, so a crafted path stored in the database
can never delete an arbitrary file. Nothing is left orphaned: every table that
references ``sessions`` (or scopes notes to a session) is cleared.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from .. import models
from ..timeutil import as_naive_utc, utc_now_naive

logger = logging.getLogger("ambisense.retention")

# Every table with a session_id foreign key, in dependency-safe order.
SESSION_CHILD_MODELS = (
    models.StudentObservation, models.AnalyticsSnapshot, models.Event, models.Alert, models.Report,
    models.AnonymousTrack, models.QualityAssessment, models.ActivitySegment, models.SpeakerSegment,
    models.DiscourseAnalysis, models.LectureChapter, models.GeneratedContentItem, models.EvidenceFusionResult,
    models.TranscriptSegment, models.AudioAnalysis, models.Notification,
)
ARTIFACT_KINDS = {"source_video", "annotated_video", "reports", "audio", "transcript_exports"}
ACTIVE_STATES = {"QUEUED", "DECODING", "INITIALIZING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "FINALIZING"}


def artifact_roots(settings) -> list[Path]:
    return [Path(folder).resolve() for folder in (settings.upload_dir, settings.report_dir)]


def is_managed_path(path: Path, settings) -> bool:
    try:
        resolved = Path(path).resolve()
        return any(resolved.is_relative_to(root) for root in artifact_roots(settings))
    except OSError:
        return False


def session_artifact_paths(db, session: models.Session, settings, kinds: set[str] | None = None) -> list[Path]:
    kinds = kinds or ARTIFACT_KINDS
    paths: list[Path] = []
    if "source_video" in kinds and session.video_path:
        paths.append(Path(session.video_path))
    if "annotated_video" in kinds:
        if session.annotated_video_path:
            paths.append(Path(session.annotated_video_path))
        paths += [Path(settings.report_dir) / f"annotated_{session.id}.mp4", Path(settings.report_dir) / f"annotated_live_{session.id}.mp4"]
    if "reports" in kinds:
        paths += [Path(value) for value in db.scalars(select(models.Report.path).where(models.Report.session_id == session.id)).all()]
        paths += [Path(settings.report_dir) / name for name in (f"session_{session.id}.csv", f"session_{session.id}.pdf", f"session_{session.id}_metrics.csv")]
    if "audio" in kinds:
        audio = db.scalar(select(models.AudioAnalysis.audio_path).where(models.AudioAnalysis.session_id == session.id))
        if audio:
            paths.append(Path(audio))
        paths.append(Path(settings.report_dir) / f"audio_{session.id}.wav")
    if "transcript_exports" in kinds:
        paths += [Path(settings.report_dir) / f"transcript_{session.id}.{extension}" for extension in ("json", "csv", "txt")]
    seen, unique = set(), []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key); unique.append(path)
    return unique


def remove_files(paths: list[Path], settings) -> dict:
    removed = failed = skipped = 0
    for path in paths:
        try:
            if not path.exists():
                continue
            if not path.is_file() or not is_managed_path(path, settings):
                skipped += 1; logger.warning("Refused to remove file outside managed directories: %s", path.name); continue
            path.unlink(); removed += 1
        except OSError:
            failed += 1; logger.warning("Could not remove artifact %s", path.name)
    return {"removed": removed, "failed": failed, "skipped_unmanaged": skipped}


def purge_session_rows(db, session_id: int) -> dict[str, int]:
    """Delete every dependent row for a session (no commit). Returns per-table counts."""
    counts: dict[str, int] = {}
    segment_ids = select(models.TranscriptSegment.id).where(models.TranscriptSegment.session_id == session_id)
    counts["transcript_corrections"] = db.execute(delete(models.TranscriptCorrection).where(models.TranscriptCorrection.segment_id.in_(segment_ids))).rowcount or 0
    for model in SESSION_CHILD_MODELS:
        counts[model.__tablename__] = db.execute(delete(model).where(model.session_id == session_id)).rowcount or 0
    counts["collaboration_notes"] = db.execute(delete(models.CollaborationNote).where(models.CollaborationNote.scope_type == "SESSION", models.CollaborationNote.scope_id == session_id)).rowcount or 0
    return counts


def delete_session(db, session: models.Session, settings, actor_id: int | None = None) -> dict:
    session_id, name = session.id, session.name
    paths = session_artifact_paths(db, session, settings)
    counts = purge_session_rows(db, session_id)
    db.delete(session)
    db.add(models.AuditEntry(actor_user_id=actor_id, action="SESSION_DELETED", resource_type="SESSION", resource_id=session_id, details={"name": name[:120], "rows_deleted": {k: v for k, v in counts.items() if v}}))
    db.commit()
    files = remove_files(paths, settings)
    logger.info("[RETENTION] deleted session %s rows=%s files=%s", session_id, sum(counts.values()), files)
    return {"status": "deleted", "session_id": session_id, "rows_deleted": counts, "artifacts": files}


def delete_artifacts(db, session: models.Session, kinds: set[str], settings, actor_id: int | None = None) -> dict:
    """Remove stored artifacts of a session while keeping its analytics evidence."""
    unknown = kinds - ARTIFACT_KINDS
    if unknown:
        raise ValueError(f"Unknown artifact kind(s): {', '.join(sorted(unknown))}")
    paths = session_artifact_paths(db, session, settings, kinds)
    if "source_video" in kinds:
        session.video_path = None
    if "annotated_video" in kinds:
        session.annotated_video_path = None
    if "reports" in kinds:
        db.execute(delete(models.Report).where(models.Report.session_id == session.id))
    if "audio" in kinds:
        audio = db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id == session.id))
        if audio:
            audio.audio_path = None
    db.add(models.AuditEntry(actor_user_id=actor_id, action="ARTIFACTS_DELETED", resource_type="SESSION", resource_id=session.id, details={"kinds": sorted(kinds)}))
    db.commit()
    return {"session_id": session.id, "kinds": sorted(kinds), "artifacts": remove_files(paths, settings)}


def retention_preview(db, settings, now: datetime | None = None) -> dict:
    """Which sessions the ``retention_days`` policy would archive. Read-only."""
    cutoff = (as_naive_utc(now) if now else utc_now_naive()) - timedelta(days=settings.retention_days)
    rows = db.scalars(select(models.Session).where(models.Session.created_at <= cutoff, models.Session.archived.is_(False), models.Session.status.notin_(list(ACTIVE_STATES)))).all()
    return {"retention_days": settings.retention_days, "cutoff": cutoff.isoformat(), "eligible_sessions": [{"id": row.id, "name": row.name, "created_at": row.created_at} for row in rows], "action": "ARCHIVE", "note": "Archiving hides sessions and keeps all evidence; it is reversible. Deletion is always an explicit per-session action."}


def apply_retention(db, settings, actor_id: int | None = None, now: datetime | None = None) -> dict:
    preview = retention_preview(db, settings, now)
    ids = [item["id"] for item in preview["eligible_sessions"]]
    for row in db.scalars(select(models.Session).where(models.Session.id.in_(ids))).all() if ids else []:
        row.archived = True
    db.add(models.AuditEntry(actor_user_id=actor_id, action="RETENTION_ARCHIVE_RUN", resource_type="SESSION", resource_id=None, details={"archived_session_ids": ids[:200], "retention_days": settings.retention_days}))
    db.commit()
    return {"archived": len(ids), "session_ids": ids, "retention_days": settings.retention_days}
