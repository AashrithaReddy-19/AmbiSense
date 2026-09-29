import csv
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app import models
from backend.app.config import get_settings
from backend.app.timeutil import utc_now_naive
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.services.audio_intelligence import derive_content, fuse, run_diarization, transcribe
from backend.app.services.cleanup import cleanup_expired_transcripts
from backend.app.services.report_generator import create_csv_report, create_pdf_report, create_transcript_export


def seed(db,name="Priority 3 completion",context="LECTURE"):
    session=models.Session(name=name,status="COMPLETED",activity_context=context);db.add(session);db.commit()
    audio=models.AudioAnalysis(session_id=session.id,status="AVAILABLE",duration=30,quality_status="GOOD",quality={"score":80,"silence_ratio":.2},coverage={"voiced_ratio":.8},updated_at=utc_now_naive())
    segment=models.TranscriptSegment(id=f"segment-{session.id}",session_id=session.id,start_seconds=2,end_seconds=9,original_text="Energy means capacity to do work?",confidence=.9,language="en",speaker_role="UNKNOWN",provider="test-adapter",generated=True,metadata_json={"anonymous":True})
    db.add_all([audio,segment,models.AnalyticsSnapshot(session_id=session.id,timestamp=9,attention_score=70,engagement_score=60)]);db.commit();derive_content(db,session.id,"AVAILABLE",audio,get_settings());fusion=fuse(db,session.id,get_settings());db.commit();return session,audio,segment,fusion


def test_retention_is_idempotent_audited_and_preserves_aggregates():
    Base.metadata.create_all(engine);settings=get_settings();previous=(settings.transcript_retention_enabled,settings.transcript_retention_days);settings.transcript_retention_enabled=True;settings.transcript_retention_days=7
    try:
        with SessionLocal() as db:
            session,audio,segment,_=seed(db,"Priority 3 expired");segment_id=segment.id;audio.updated_at=utc_now_naive()-timedelta(days=8);db.commit();discourse_id=db.scalar(select(models.DiscourseAnalysis.id).where(models.DiscourseAnalysis.session_id==session.id))
            first=cleanup_expired_transcripts(db,settings);second=cleanup_expired_transcripts(db,settings)
            assert first["changed"]==1 and second["changed"]==0
            assert db.get(models.AudioAnalysis,audio.id).status=="RETENTION_DELETED"
            assert db.get(models.TranscriptSegment,segment_id) is None and db.get(models.DiscourseAnalysis,discourse_id)
            assert db.scalar(select(models.CleanupAudit.id).where(models.CleanupAudit.session_id==session.id,models.CleanupAudit.action=="TRANSCRIPT_RETENTION"))
    finally: settings.transcript_retention_enabled,settings.transcript_retention_days=previous


def test_retention_disabled_and_nonexpired_preserved():
    settings=get_settings();previous=settings.transcript_retention_enabled;settings.transcript_retention_enabled=False
    try:
        with SessionLocal() as db:
            session,_,segment,_=seed(db,"Priority 3 retention disabled");assert cleanup_expired_transcripts(db,settings)["status"]=="DISABLED";assert db.get(models.TranscriptSegment,segment.id)
    finally: settings.transcript_retention_enabled=previous


def test_exports_corrections_roles_and_reports_are_valid():
    with SessionLocal() as db:
        session,_,segment,_=seed(db,"Priority 3 exports")
        segment.corrected_text="Energy is the capacity to do work.";db.add(models.TranscriptCorrection(segment_id=segment.id,previous_text=segment.original_text,corrected_text=segment.corrected_text));db.commit()
        json_path=create_transcript_export(db,session.id,"json");csv_path=create_transcript_export(db,session.id,"csv");text_path=create_transcript_export(db,session.id,"txt")
        assert json.loads(json_path.read_text(encoding="utf-8"))["segments"][0]["correction_status"]=="HUMAN_CORRECTED"
        with csv_path.open(encoding="utf-8") as stream: assert next(csv.DictReader(stream))["speaker_role"]=="UNKNOWN"
        assert "[2.000-9.000]" in text_path.read_text(encoding="utf-8")
        report_csv=create_csv_report(db,session.id);assert "fusion_context" in report_csv.read_text(encoding="utf-8")
        assert create_pdf_report(db,session.id).stat().st_size>500
        session_id=session.id;segment_id=segment.id
    with TestClient(app) as client:
        role=client.put(f"/api/v1/transcript-segments/{segment_id}/speaker-role",json={"role":"INSTRUCTOR"});assert role.status_code==200 and role.json()["cross_session_matching"] is False
        assert client.get(f"/api/v1/transcript-segments/{segment_id}/corrections").json()
        assert client.post("/api/v1/search",json={"query":"show engagement; drop table sessions"}).status_code==400
        assert client.get(f"/api/v1/sessions/{session_id}/transcript/export?format=json").status_code==200


def test_context_rules_missing_audio_and_reviewer_exclusion():
    with SessionLocal() as db:
        lecture,_,_,lecture_fusion=seed(db,"Priority 3 lecture","LECTURE")
        discussion,_,_,discussion_fusion=seed(db,"Priority 3 discussion","GROUP_DISCUSSION")
        exam,_,_,exam_fusion=seed(db,"Priority 3 exam","EXAMINATION")
        assert lecture_fusion.coverage["context"]=="LECTURE" and discussion_fusion.coverage["context"]=="GROUP_DISCUSSION"
        assert next(c for c in exam_fusion.components if c["name"]=="visual_orientation")["included"] is False
        db.add(models.Event(session_id=lecture.id,timestamp=1,event_type="HAND_RAISED",severity="INFO",message="anonymous",review_state="EXCLUDED",included_in_report=False));db.commit();reviewed=fuse(db,lecture.id,get_settings());db.commit()
        excluded=next(c for c in reviewed.components if c["name"]=="observable_participation");assert excluded["included"] is False and "Reviewer excluded" in excluded["exclusion_reason"]
        audio=db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id==discussion.id));audio.status="MODEL_DISABLED";db.commit();missing=fuse(db,discussion.id,get_settings());db.commit();assert abs(sum(c["effective_weight"] for c in missing.components if c["included"])-1)<.001


def test_transcription_unavailable_is_idempotent_and_never_fabricates():
    settings=get_settings();previous=settings.transcription_provider;settings.transcription_provider="LOCAL_MISSING"
    try:
        with SessionLocal() as db:
            session=models.Session(name="Priority 3 missing model",status="COMPLETED");db.add(session);db.commit();audio=models.AudioAnalysis(session_id=session.id,status="AVAILABLE",audio_path="missing.wav");db.add(audio);db.commit()
            assert transcribe(db,session.id,audio,settings)=="MODEL_UNAVAILABLE";assert transcribe(db,session.id,audio,settings)=="MODEL_UNAVAILABLE";assert db.query(models.TranscriptSegment).filter_by(session_id=session.id).count()==0
    finally: settings.transcription_provider=previous


def test_anonymous_diarization_adapter_discards_identity_labels():
    class Stub:
        name="stub";model_version="1"
        def segment(self,_path): return [{"start":0,"end":2,"confidence":.8,"provider_identity":"Alice"}]
    settings=get_settings();previous=settings.diarization_provider;settings.diarization_provider="LOCAL_ADAPTER"
    try:
        with SessionLocal() as db:
            session=models.Session(name="Priority 3 anonymous diarization",status="COMPLETED");db.add(session);db.commit();audio=models.AudioAnalysis(session_id=session.id,status="AVAILABLE",audio_path="unused.wav");db.add(audio);db.commit()
            assert run_diarization(db,session.id,audio,settings,Stub())=="AVAILABLE";db.commit();row=db.scalar(select(models.SpeakerSegment).where(models.SpeakerSegment.session_id==session.id));assert row.role=="UNKNOWN" and not hasattr(row,"provider_identity")
    finally: settings.diarization_provider=previous
