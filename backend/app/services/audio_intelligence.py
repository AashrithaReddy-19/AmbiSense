"""Optional, privacy-preserving audio and transcript intelligence.

No adapter in this module invents speech. Disabled or unavailable dependencies are
persisted as explicit states while the visual pipeline remains successful.
"""
from __future__ import annotations

import importlib.util
import math
import re
import shutil
import subprocess
import uuid
import wave
from collections import Counter
from pathlib import Path
from typing import Protocol

import numpy as np
from sqlalchemy import delete, select

from .. import models


class Transcriber(Protocol):
    name: str
    model_version: str
    def transcribe(self, audio_path: Path) -> list[dict]: ...


class Diarizer(Protocol):
    """Anonymous, session-local segmentation only; identity labels are discarded."""
    name: str
    model_version: str
    def segment(self, audio_path: Path) -> list[dict]: ...


class FasterWhisperTranscriber:
    name = "faster-whisper"
    def __init__(self, model: str, language: str = "auto"):
        from faster_whisper import WhisperModel
        self.model_version = model
        self.language = None if language == "auto" else language
        self.model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: Path) -> list[dict]:
        segments, info = self.model.transcribe(str(audio_path), language=self.language, vad_filter=True)
        return [{"start": float(s.start), "end": float(s.end), "text": s.text.strip(),
                 "confidence": max(0.0, min(1.0, math.exp(float(s.avg_logprob)))),
                 "language": getattr(info, "language", None)} for s in segments if s.text.strip()]


def _state(db, session_id: int, **values):
    row = db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id == session_id))
    if not row:
        row = models.AudioAnalysis(session_id=session_id)
        db.add(row)
    for key, value in values.items(): setattr(row, key, value)
    return row


def extract_and_analyze(db, session, settings) -> models.AudioAnalysis:
    if not settings.audio_analytics_enabled:
        return _state(db, session.id, status="MODEL_DISABLED", quality_status="UNAVAILABLE",
                      limitations=["Audio analytics are disabled by configuration."])
    if not session.video_path or not Path(session.video_path).exists():
        return _state(db, session.id, status="UNAVAILABLE", limitations=["Source media is unavailable."])
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return _state(db, session.id, status="MODEL_UNAVAILABLE", limitations=["FFmpeg is not installed or not on PATH."])
    destination = settings.report_dir / f"audio_{session.id}.wav"
    command = [ffmpeg, "-y", "-i", session.video_path, "-vn", "-ac", "1", "-ar",
               str(settings.audio_sample_rate), "-c:a", "pcm_s16le", str(destination)]
    result = subprocess.run(command, capture_output=True, timeout=max(60, int(session.duration * 2 + 30)))
    if result.returncode or not destination.exists():
        return _state(db, session.id, status="UNAVAILABLE", limitations=["No decodable audio stream was found."])
    with wave.open(str(destination), "rb") as stream:
        sample_rate = stream.getframerate(); samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    duration = len(samples) / sample_rate if sample_rate else 0
    if not len(samples):
        return _state(db, session.id, status="UNAVAILABLE", audio_path=str(destination), limitations=["Audio stream is empty."])
    window = max(1, int(sample_rate * .1)); rms = np.array([np.sqrt(np.mean(part * part)) for part in np.array_split(samples, max(1, len(samples)//window))])
    voiced = rms >= settings.audio_vad_threshold
    voice_ratio = float(np.mean(voiced)); clipping = float(np.mean(np.abs(samples) >= .98)); silence = 1 - voice_ratio
    noise_floor = float(np.percentile(rms, 20)); signal = float(np.percentile(rms, 80)); snr = 20 * math.log10(max(signal, 1e-8) / max(noise_floor, 1e-8))
    score = max(0, min(100, 100 - silence * 35 - clipping * 300 - max(0, 15-snr)*2))
    status = "GOOD" if score >= 70 else "LIMITED" if score >= 40 else "POOR"
    return _state(db, session.id, status="AVAILABLE", audio_path=str(destination), duration=duration,
                  sample_rate=sample_rate, quality_status=status,
                  quality={"score": round(score,2), "snr_db_estimate": round(snr,2), "clipping_ratio": round(clipping,4), "silence_ratio": round(silence,4)},
                  coverage={"audio_duration_seconds": round(duration,3), "voiced_ratio": round(voice_ratio,4)}, limitations=[])


def transcribe(db, session_id: int, analysis: models.AudioAnalysis, settings) -> str:
    db.execute(delete(models.TranscriptSegment).where(models.TranscriptSegment.session_id == session_id))
    provider = settings.transcription_provider.strip().upper()
    if analysis.status != "AVAILABLE": return "UNAVAILABLE"
    if provider in {"", "NONE", "DISABLED"}:
        analysis.provider = "NONE"; analysis.limitations = [*analysis.limitations, "Transcription is disabled; no transcript was generated."]
        return "MODEL_DISABLED"
    if provider != "FASTER_WHISPER" or importlib.util.find_spec("faster_whisper") is None:
        analysis.provider = provider; analysis.limitations = [*analysis.limitations, f"Transcription provider {provider} is unavailable."]
        return "MODEL_UNAVAILABLE"
    adapter = FasterWhisperTranscriber(settings.transcription_model, settings.transcription_language)
    for item in adapter.transcribe(Path(analysis.audio_path)):
        db.add(models.TranscriptSegment(id=str(uuid.uuid4()), session_id=session_id, start_seconds=item["start"], end_seconds=item["end"], original_text=item["text"], confidence=item["confidence"], language=item["language"], speaker_role="UNKNOWN", provider=adapter.name, model_version=adapter.model_version, metadata_json={"privacy":"anonymous"}))
    analysis.provider=adapter.name; analysis.model_version=adapter.model_version
    return "AVAILABLE"


def run_diarization(db, session_id: int, analysis: models.AudioAnalysis, settings, adapter: Diarizer | None = None) -> str:
    db.execute(delete(models.SpeakerSegment).where(models.SpeakerSegment.session_id==session_id))
    if settings.diarization_provider=="NONE": return "MODEL_DISABLED"
    if analysis.status!="AVAILABLE" or adapter is None: return "MODEL_UNAVAILABLE"
    for item in adapter.segment(Path(analysis.audio_path)):
        # Provider cluster/identity labels are intentionally not persisted.
        db.add(models.SpeakerSegment(session_id=session_id,start_seconds=float(item["start"]),end_seconds=float(item["end"]),role="UNKNOWN",confidence=item.get("confidence")))
    return "AVAILABLE"


def derive_content(db, session_id: int, transcript_status: str, analysis: models.AudioAnalysis, settings):
    for model in (models.DiscourseAnalysis, models.LectureChapter, models.GeneratedContentItem, models.EvidenceFusionResult):
        db.execute(delete(model).where(model.session_id == session_id))
    segments = db.scalars(select(models.TranscriptSegment).where(models.TranscriptSegment.session_id == session_id).order_by(models.TranscriptSegment.start_seconds)).all()
    if not segments:
        db.add(models.DiscourseAnalysis(session_id=session_id, status=transcript_status, metrics={"question_count": None, "speaking_time_seconds": None}, limitations=["A transcript is required for discourse and lecture-content analysis."]))
        return
    speaking = sum(max(0, s.end_seconds-s.start_seconds) for s in segments); duration=max(analysis.duration, segments[-1].end_seconds, .001)
    questions=sum((s.corrected_text or s.original_text).count("?") for s in segments)
    db.add(models.DiscourseAnalysis(session_id=session_id,status="AVAILABLE",metrics={"speaking_time_seconds":{"value":round(speaking,2),"coverage":round(speaking/duration,3),"confidence":.8},"silence_ratio":{"value":analysis.quality.get("silence_ratio"),"coverage":1,"confidence":.7},"question_count":{"value":questions,"coverage":round(speaking/duration,3),"confidence":.65},"speaker_roles":{"value":"UNKNOWN","confidence":0}},limitations=["Speaker roles remain UNKNOWN unless explicitly configured; no identity inference is performed."]))
    text_items=[(s.corrected_text or s.original_text).strip() for s in segments]
    stop={"the","and","that","this","with","from","have","will","your","are","was","for","you","not","but","can","into","then","they"}
    terms=Counter(w.lower() for t in text_items for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}",t) if w.lower() not in stop)
    chunks=[segments[i:i+8] for i in range(0,len(segments),8)]
    for chunk in chunks:
        words=Counter(w.lower() for s in chunk for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}",s.original_text) if w.lower() not in stop)
        title=" / ".join(w.title() for w,_ in words.most_common(3)) or "Lecture segment"
        db.add(models.LectureChapter(session_id=session_id,title=title,start_seconds=chunk[0].start_seconds,end_seconds=chunk[-1].end_seconds,confidence=.6,evidence_segment_ids=[s.id for s in chunk]))
    items=[]
    if text_items: items.append(("SUMMARY",text_items[0],segments[:1],.7))
    for term,count in terms.most_common(10): items.append(("KEY_TERM",f"{term} ({count} mentions)",segments,.6))
    for s in segments:
        text=s.corrected_text or s.original_text
        if re.search(r"\b(is defined as|means|refers to)\b",text,re.I): items.append(("DEFINITION",text,[s],.7))
        if "?" in text: items.append(("QUESTION",text,[s],.75))
    for ordinal,(kind,text,evidence,confidence) in enumerate(items):
        db.add(models.GeneratedContentItem(session_id=session_id,content_type=kind,ordinal=ordinal,text=text,confidence=confidence,evidence_segment_ids=[s.id for s in evidence],timestamps=[s.start_seconds for s in evidence[:5]],provider="DETERMINISTIC_EXTRACTIVE",generated=True))


def fuse(db, session_id: int, settings):
    db.execute(delete(models.EvidenceFusionResult).where(models.EvidenceFusionResult.session_id==session_id,models.EvidenceFusionResult.methodology_version==settings.evidence_fusion_version))
    session=db.get(models.Session,session_id); context=session.activity_context if session else "LECTURE"
    latest_activity=db.scalar(select(models.ActivitySegment).where(models.ActivitySegment.session_id==session_id,models.ActivitySegment.confirmed.is_(True)).order_by(models.ActivitySegment.start_seconds.desc()))
    if latest_activity: context=latest_activity.activity_type
    snapshot=db.scalar(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id==session_id).order_by(models.AnalyticsSnapshot.timestamp.desc()))
    audio=db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id==session_id)); discourse=db.scalar(select(models.DiscourseAnalysis).where(models.DiscourseAnalysis.session_id==session_id))
    rules={
        "LECTURE":{"visual_orientation":.50,"observable_participation":.30,"audio_quality":.10,"discourse_coverage":.10},
        "GROUP_DISCUSSION":{"visual_orientation":.15,"observable_participation":.30,"audio_quality":.15,"discourse_coverage":.40},
        "STUDENT_PRESENTATION":{"visual_orientation":.30,"observable_participation":.25,"audio_quality":.15,"discourse_coverage":.30},
        "EXAMINATION":{"visual_orientation":0,"observable_participation":.80,"audio_quality":.20,"discourse_coverage":0},
        "INDEPENDENT_WRITING":{"visual_orientation":0,"observable_participation":.80,"audio_quality":.20,"discourse_coverage":0},
        "READING":{"visual_orientation":0,"observable_participation":.75,"audio_quality":.25,"discourse_coverage":0},
        "VIDEO_SCREENING":{"visual_orientation":.50,"observable_participation":.30,"audio_quality":.20,"discourse_coverage":0},
        "BREAK":{"visual_orientation":0,"observable_participation":0,"audio_quality":0,"discourse_coverage":0},
    }; weights=rules.get(context,rules["LECTURE"])
    raw=[]
    if snapshot: raw += [("visual_orientation",snapshot.attention_score,.75),("observable_participation",snapshot.engagement_score,.70)]
    if audio and audio.status=="AVAILABLE": raw.append(("audio_quality",audio.quality.get("score"),.70))
    if discourse and discourse.status=="AVAILABLE":
        coverage=discourse.metrics.get("speaking_time_seconds",{}).get("coverage"); raw.append(("discourse_coverage",coverage*100 if coverage is not None else None,.65))
    excluded_events=db.scalars(select(models.Event).where(models.Event.session_id==session_id,models.Event.review_state.in_(["INCORRECT","EXCLUDED"]))).all()
    components=[]; valid=[]
    for name,value,confidence in raw:
        weight=weights.get(name,0)
        reason=None
        if weight<=0: reason=f"{name.replace('_',' ')} is not relevant for {context}."
        if name=="observable_participation" and excluded_events: reason=f"Reviewer excluded {len(excluded_events)} related event(s); participation evidence was excluded."
        if value is None: reason="Evidence value is unavailable."
        if confidence<.5: reason="Evidence confidence is below the inclusion threshold."
        if reason: components.append({"name":name,"value":value,"configured_weight":weight,"effective_weight":0,"confidence":confidence,"included":False,"exclusion_reason":reason})
        else: valid.append((name,value,weight,confidence))
    total=sum(x[2] for x in valid)
    for name,value,weight,confidence in valid: components.append({"name":name,"value":round(value,2),"configured_weight":weight,"effective_weight":round(weight/total,4),"confidence":confidence,"included":True,"exclusion_reason":None})
    value=sum(x[1]*x[2]/total for x in valid) if total else None
    row=models.EvidenceFusionResult(session_id=session_id,methodology_version=settings.evidence_fusion_version,status="AVAILABLE" if value is not None else "INSUFFICIENT_EVIDENCE",value=round(value,2) if value is not None else None,confidence=round(sum(x[3]*x[2]/total for x in valid),3) if total else None,coverage={"included":len(valid),"candidate":len(raw),"excluded":len(components)-len(valid),"context":context},components=components,limitations=[] if value is not None else [f"No relevant, sufficiently supported evidence was available for {context}."],weights=weights)
    db.add(row); return row


def run_audio_intelligence(db, session, settings):
    analysis=extract_and_analyze(db,session,settings); db.flush()
    status=transcribe(db,session.id,analysis,settings); run_diarization(db,session.id,analysis,settings); derive_content(db,session.id,status,analysis,settings); fuse(db,session.id,settings); db.commit()
