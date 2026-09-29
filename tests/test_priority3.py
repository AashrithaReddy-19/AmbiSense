from fastapi.testclient import TestClient

from backend.app import models
from backend.app.config import get_settings
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.services.audio_intelligence import derive_content, fuse, transcribe


def test_disabled_transcription_never_fabricates_text():
    Base.metadata.create_all(engine)
    settings=get_settings(); previous=settings.transcription_provider; settings.transcription_provider="NONE"
    try:
        with SessionLocal() as db:
            session=models.Session(name="Priority 3 disabled transcript",status="COMPLETED")
            db.add(session); db.commit()
            analysis=models.AudioAnalysis(session_id=session.id,status="AVAILABLE",duration=10,audio_path="missing.wav")
            db.add(analysis); db.commit()
            assert transcribe(db,session.id,analysis,settings)=="MODEL_DISABLED"
            assert db.query(models.TranscriptSegment).filter_by(session_id=session.id).count()==0
    finally: settings.transcription_provider=previous


def test_grounded_content_fusion_and_api_evidence():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        session=models.Session(name="Priority 3 grounded evidence",status="COMPLETED")
        db.add(session); db.commit()
        analysis=models.AudioAnalysis(session_id=session.id,status="AVAILABLE",duration=20,quality_status="GOOD",quality={"score":80,"silence_ratio":.2},coverage={"voiced_ratio":.8})
        db.add(analysis)
        segment=models.TranscriptSegment(id=f"p3-segment-{session.id}",session_id=session.id,start_seconds=1,end_seconds=7,original_text="Photosynthesis means converting light into chemical energy. Why is chlorophyll important?",confidence=.9,language="en",speaker_role="UNKNOWN",provider="test-real-adapter",generated=True)
        db.add(segment); db.add(models.AnalyticsSnapshot(session_id=session.id,timestamp=7,attention_score=70,engagement_score=60)); db.commit()
        derive_content(db,session.id,"AVAILABLE",analysis,get_settings()); fusion=fuse(db,session.id,get_settings()); db.commit(); session_id=session.id
        assert fusion.value is not None
        assert all(item.evidence_segment_ids for item in db.query(models.GeneratedContentItem).filter_by(session_id=session_id))
    with TestClient(app) as client:
        transcript=client.get(f"/api/v1/sessions/{session_id}/transcript").json(); assert transcript["segments"][0]["speaker_role"]=="UNKNOWN"
        content=client.get(f"/api/v1/sessions/{session_id}/content").json(); assert content["status"]=="AVAILABLE"
        graph=client.get(f"/api/v1/sessions/{session_id}/evidence-graph").json(); assert graph["status"]=="AVAILABLE" and graph["edges"]
        search=client.post("/api/v1/search",json={"query":f"concept chlorophyll session {session_id}","data_source":"ALL"}).json(); assert search["matches"][0]["evidence_segment_id"]==f"p3-segment-{session_id}"
