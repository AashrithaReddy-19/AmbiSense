"""Idempotent development cleanup for explicitly marked API/test sessions only."""
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select

from .. import models


def cleanup_test_sessions(db, settings, now: datetime | None = None) -> dict:
    run_id=str(uuid4()); now=now or datetime.utcnow()
    if not settings.test_session_cleanup_enabled:
        return {"run_id":run_id,"status":"DISABLED","eligible":0,"changed":0}
    cutoff=now-timedelta(hours=max(1,settings.test_session_cleanup_age_hours)); action=settings.test_session_cleanup_action.upper()
    if action not in {"ARCHIVE","DELETE"}: raise ValueError("TEST_SESSION_CLEANUP_ACTION must be ARCHIVE or DELETE")
    rows=db.scalars(select(models.Session).where(models.Session.is_test.is_(True),models.Session.created_at<=cutoff,models.Session.status.notin_(["INITIALIZING","PROCESSING","FINALIZING"]))).all(); changed=0
    for row in rows:
        if action=="ARCHIVE":
            if row.archived: continue
            row.archived=True; changed+=1
        else:
            paths=[Path(value) for value in (row.video_path,row.annotated_video_path) if value]
            segment_ids=select(models.TranscriptSegment.id).where(models.TranscriptSegment.session_id==row.id)
            db.execute(delete(models.TranscriptCorrection).where(models.TranscriptCorrection.segment_id.in_(segment_ids)))
            for model in (models.StudentObservation,models.AnalyticsSnapshot,models.Event,models.Alert,models.Report,models.AnonymousTrack,models.QualityAssessment,models.ActivitySegment,models.SpeakerSegment,models.DiscourseAnalysis,models.LectureChapter,models.GeneratedContentItem,models.EvidenceFusionResult,models.TranscriptSegment,models.AudioAnalysis):
                db.execute(delete(model).where(model.session_id==row.id))
            db.delete(row); changed+=1
            for path in paths:
                try:
                    resolved=path.resolve()
                    if path.is_file() and (resolved.is_relative_to(settings.upload_dir.resolve()) or resolved.is_relative_to(settings.report_dir.resolve())): path.unlink(missing_ok=True)
                except OSError: pass
        db.add(models.CleanupAudit(run_id=run_id,session_id=row.id,action=action,result="CHANGED",details={"name":row.name,"cutoff":cutoff.isoformat()}))
    db.add(models.CleanupAudit(run_id=run_id,action=action,result="SUMMARY",details={"eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat()})); db.commit()
    return {"run_id":run_id,"status":"COMPLETED","action":action,"eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat()}


def cleanup_expired_transcripts(db, settings, now: datetime | None = None) -> dict:
    """Remove raw audio/transcript evidence while preserving aggregate analytics."""
    run_id=str(uuid4()); now=now or datetime.utcnow()
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
    db.add(models.CleanupAudit(run_id=run_id,action="TRANSCRIPT_RETENTION",result="SUMMARY",details={"eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat()})); db.commit()
    return {"run_id":run_id,"status":"COMPLETED","eligible":len(rows),"changed":changed,"cutoff":cutoff.isoformat()}
