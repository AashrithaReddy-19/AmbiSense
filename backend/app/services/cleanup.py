"""Idempotent development cleanup for explicitly marked API/test sessions only."""
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select

from .. import models
from ..timeutil import as_naive_utc, utc_now_naive
from .retention import purge_session_rows, remove_files, session_artifact_paths


def _test_session_candidates(db, settings, now: datetime):
    cutoff=now-timedelta(hours=max(1,settings.test_session_cleanup_age_hours)); action=settings.test_session_cleanup_action.upper()
    if action not in {"ARCHIVE","DELETE"}: raise ValueError("TEST_SESSION_CLEANUP_ACTION must be ARCHIVE or DELETE")
    rows=db.scalars(select(models.Session).where(models.Session.is_test.is_(True),models.Session.created_at<=cutoff,models.Session.status.notin_(["INITIALIZING","PROCESSING","FINALIZING"]))).all()
    return cutoff,action,rows


def preview_test_session_cleanup(db, settings, now: datetime | None = None) -> dict:
    """What a cleanup run would do, right now. Read-only: no session change and no audit row, whatever the configuration."""
    cutoff,action,rows=_test_session_candidates(db,settings,as_naive_utc(now) if now else utc_now_naive())
    affected=[row for row in rows if action=="DELETE" or not row.archived]
    return {"status":"PREVIEW","action":action,"scheduled":bool(settings.scheduled_cleanup_enabled and settings.test_session_cleanup_enabled),"cutoff":cutoff.isoformat(),"eligible":len(affected),
            "sessions":[{"id":row.id,"name":row.name,"status":row.status,"created_at":row.created_at.isoformat() if row.created_at else None,"archived":bool(row.archived)} for row in affected],
            "note":"Nothing was changed. ARCHIVE hides the sessions (reversible); DELETE permanently removes them and their managed files."}


def cleanup_test_sessions(db, settings, now: datetime | None = None, manual: bool = False) -> dict:
    """Archive/delete sessions flagged as tests. `manual=True` is an explicit, confirmed administrator action and applies
    even when the scheduled policy flag is off; scheduled callers leave it False and honour the flag."""
    run_id=str(uuid4()); now=as_naive_utc(now) if now else utc_now_naive()
    if not manual and not settings.test_session_cleanup_enabled:
        return {"run_id":run_id,"status":"DISABLED","eligible":0,"changed":0}
    cutoff,action,rows=_test_session_candidates(db,settings,now); changed=0; pending_files=[]
    for row in rows:
        if action=="ARCHIVE":
            if row.archived: continue
            row.archived=True; changed+=1
        else:
            # Shared with the API delete path: clears every dependent table
            # (including notifications/notes) and removes managed artifact files.
            paths=session_artifact_paths(db,row,settings); purge_session_rows(db,row.id)
            db.delete(row); changed+=1; pending_files.extend(paths)
        db.add(models.CleanupAudit(run_id=run_id,session_id=row.id,action=action,result="CHANGED",details={"name":row.name,"cutoff":cutoff.isoformat(),"trigger":"MANUAL" if manual else "SCHEDULED"}))
    if changed or manual: db.add(models.CleanupAudit(run_id=run_id,action=action,result="SUMMARY",details={"eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat(),"trigger":"MANUAL" if manual else "SCHEDULED"}))
    db.commit()
    remove_files(pending_files,settings)
    return {"run_id":run_id,"status":"COMPLETED","action":action,"eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat()}


def cleanup_expired_transcripts(db, settings, now: datetime | None = None) -> dict:
    """Remove raw audio/transcript evidence while preserving aggregate analytics."""
    run_id=str(uuid4()); now=as_naive_utc(now) if now else utc_now_naive()
    if not settings.transcript_retention_enabled or settings.transcript_retention_days <= 0:
        return {"run_id":run_id,"status":"DISABLED","eligible":0,"changed":0}
    cutoff=now-timedelta(days=settings.transcript_retention_days)
    rows=db.scalars(select(models.AudioAnalysis).where(models.AudioAnalysis.updated_at<=cutoff,models.AudioAnalysis.status.notin_(["RETENTION_DELETED"]))).all(); changed=0
    for audio in rows:
        session_id=audio.session_id
        segment_ids=select(models.TranscriptSegment.id).where(models.TranscriptSegment.session_id==session_id)
        db.execute(delete(models.TranscriptCorrection).where(models.TranscriptCorrection.segment_id.in_(segment_ids)))
        for model in (models.LectureChapter,models.GeneratedContentItem,models.SpeakerSegment,models.TranscriptSegment):
            db.execute(delete(model).where(model.session_id==session_id))
        removed_audio=False
        if audio.audio_path:
            path=Path(audio.audio_path)
            try:
                resolved=path.resolve()
                if path.is_file() and resolved.is_relative_to(settings.report_dir.resolve()): path.unlink(missing_ok=True); removed_audio=True
            except OSError: pass
        audio.audio_path=None; audio.status="RETENTION_DELETED"; audio.provider=None; audio.model_version=None
        audio.limitations=["Raw audio and transcript evidence were removed by the configured retention policy."]
        db.add(models.CleanupAudit(run_id=run_id,session_id=session_id,action="TRANSCRIPT_RETENTION",result="CHANGED",details={"cutoff":cutoff.isoformat(),"audio_removed":removed_audio,"aggregates_preserved":True}))
        changed+=1
    if changed: db.add(models.CleanupAudit(run_id=run_id,action="TRANSCRIPT_RETENTION",result="SUMMARY",details={"eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat()}))
    db.commit()
    return {"run_id":run_id,"status":"COMPLETED","eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat()}
