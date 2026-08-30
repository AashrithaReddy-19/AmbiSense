import csv
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from .. import models
from ..models import AnalyticsSnapshot, Event
from ..crud import session_summary


def create_csv_report(db: Session, session_id: int) -> Path:
    rows = db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.session_id == session_id).order_by(AnalyticsSnapshot.timestamp)).all()
    path = get_settings().report_dir / f"session_{session_id}.csv"
    audio=db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id==session_id)); discourse=db.scalar(select(models.DiscourseAnalysis).where(models.DiscourseAnalysis.session_id==session_id)); fusion=db.scalar(select(models.EvidenceFusionResult).where(models.EvidenceFusionResult.session_id==session_id).order_by(models.EvidenceFusionResult.id.desc()))
    fields = ["timestamp", "student_count", "current_occupancy_count", "peak_occupancy_count", "occupancy_rate", "estimated_unique_tracks", "verified_attendance_rate", "attention_score", "engagement_score", "fatigue_score", "drowsiness_count", "yawning_count", "raised_hands", "distracted_students", "looking_down_students", "looking_away_students", "occupied_seats", "empty_seats", "noise_level","audio_status","audio_quality_status","audio_quality_score","voice_coverage","discourse_status","question_count","fusion_status","fusion_value","fusion_confidence","fusion_context","fusion_limitations"]
    extras={"audio_status":audio.status if audio else "NOT_PROCESSED","audio_quality_status":audio.quality_status if audio else "UNAVAILABLE","audio_quality_score":audio.quality.get("score") if audio else None,"voice_coverage":audio.coverage.get("voiced_ratio") if audio else None,"discourse_status":discourse.status if discourse else "NOT_PROCESSED","question_count":discourse.metrics.get("question_count",{}).get("value") if discourse and isinstance(discourse.metrics.get("question_count"),dict) else None,"fusion_status":fusion.status if fusion else "NOT_PROCESSED","fusion_value":fusion.value if fusion else None,"fusion_confidence":fusion.confidence if fusion else None,"fusion_context":fusion.coverage.get("context") if fusion else None,"fusion_limitations":" | ".join(fusion.limitations) if fusion else "Evidence fusion has not run."}
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        data=[{**{field:getattr(row,field) for field in fields if hasattr(row,field)},**extras} for row in rows]
        writer.writerows(data or [{**{field:None for field in fields},**extras}])
    return path


def create_pdf_report(db: Session, session_id: int) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    summary = session_summary(db, session_id)
    rows = db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.session_id == session_id).order_by(AnalyticsSnapshot.timestamp)).all()
    path = get_settings().report_dir / f"session_{session_id}.pdf"
    canvas = Canvas(str(path), pagesize=A4)
    width, height = A4
    canvas.setTitle(f"AmbiSense Session {session_id}")
    canvas.setFont("Helvetica-Bold", 22)
    canvas.drawString(52, height - 65, "AMBISENSE")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(52, height - 82, "Ambient Classroom Intelligence & Engagement Suite")
    canvas.line(52, height - 95, width - 52, height - 95)
    y = height - 125
    for key, value in summary.items():
        if key == "recommendations":
            continue
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(52, y, key.replace("_", " ").title())
        canvas.setFont("Helvetica", 10)
        canvas.drawString(230, y, str(value))
        y -= 20
    y -= 10
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(52, y, "Evidence-based notes")
    for note in summary.get("recommendations", []):
        y -= 19
        canvas.setFont("Helvetica", 9)
        canvas.drawString(62, y, f"- {note}")
    if rows:
        y -= 28
        canvas.setFont("Helvetica-Bold", 12); canvas.drawString(52, y, "Analytics timeline")
        chart_x, chart_y, chart_w, chart_h = 52, y - 145, width - 104, 120
        canvas.rect(chart_x, chart_y, chart_w, chart_h)
        colors = [(0.19, .85, .63), (.35, .66, 1), (.98, .44, .52)]
        fields = ["engagement_score", "attention_score", "fatigue_score"]
        for color, field in zip(colors, fields):
            canvas.setStrokeColorRGB(*color)
            points = []
            for index, row in enumerate(rows):
                x = chart_x + index / max(len(rows) - 1, 1) * chart_w
                value = max(0, min(100, float(getattr(row, field))))
                points.append((x, chart_y + value / 100 * chart_h))
            for first, second in zip(points, points[1:]): canvas.line(*first, *second)
        y = chart_y - 24
        canvas.setFillColorRGB(0, 0, 0); canvas.setFont("Helvetica", 8)
        canvas.drawString(52, y, "Green: Estimated Engagement | Blue: Visual Attention | Red: Fatigue Indicators")
    events = db.scalars(select(Event).where(Event.session_id == session_id, Event.included_in_report.is_(True)).limit(12)).all()
    if events and y > 100:
        y -= 24; canvas.setFont("Helvetica-Bold", 11); canvas.drawString(52, y, "Important events")
        for event in events:
            y -= 14; canvas.setFont("Helvetica", 8); canvas.drawString(60, y, f"{event.timestamp:.1f}s - {event.event_type}: {event.message}"[:100])
    y -= 24; canvas.setFont("Helvetica-Bold", 10); canvas.drawString(52, max(70, y), "Methodology and privacy")
    canvas.setFont("Helvetica", 7); canvas.drawString(52, max(58, y - 12), "Anonymous YOLO tracking; landmark-derived head pose, EAR/MAR and pose participation. No face identity or face crops are stored.")
    canvas.setFont("Helvetica-Oblique", 8)
    canvas.drawString(52, 42, "Analytics are estimates for educational research, not medical or pedagogical diagnoses.")
    audio=db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id==session_id)); discourse=db.scalar(select(models.DiscourseAnalysis).where(models.DiscourseAnalysis.session_id==session_id)); fusion=db.scalar(select(models.EvidenceFusionResult).where(models.EvidenceFusionResult.session_id==session_id).order_by(models.EvidenceFusionResult.id.desc())); chapters=db.scalars(select(models.LectureChapter).where(models.LectureChapter.session_id==session_id).order_by(models.LectureChapter.start_seconds).limit(8)).all(); content=db.scalars(select(models.GeneratedContentItem).where(models.GeneratedContentItem.session_id==session_id).order_by(models.GeneratedContentItem.ordinal).limit(10)).all()
    canvas.showPage(); y=height-60; canvas.setFont("Helvetica-Bold",16); canvas.drawString(52,y,"Audio, discourse, and evidence")
    lines=[f"Audio: {audio.status if audio else 'NOT_PROCESSED'}",f"Audio quality: {audio.quality_status if audio else 'UNAVAILABLE'}",f"Voice coverage: {audio.coverage.get('voiced_ratio') if audio else 'Unavailable'}",f"Discourse: {discourse.status if discourse else 'NOT_PROCESSED'}",f"Transcript: {'AVAILABLE' if content or chapters else 'UNAVAILABLE'}",f"Fusion: {fusion.value if fusion and fusion.value is not None else 'Insufficient evidence'}",f"Fusion confidence: {fusion.confidence if fusion else 'Unavailable'}",f"Context: {fusion.coverage.get('context') if fusion else 'Unavailable'}"]
    for line in lines: y-=18; canvas.setFont("Helvetica",9); canvas.drawString(52,y,line[:110])
    if fusion:
        y-=16; canvas.setFont("Helvetica-Bold",11); canvas.drawString(52,y,"Evidence Graph summary")
        for component in fusion.components:
            y-=14; state="included" if component.get("included",True) else f"excluded: {component.get('exclusion_reason')}"; canvas.setFont("Helvetica",8); canvas.drawString(60,y,f"{component['name']}: {state}; confidence {component.get('confidence')}; coverage weight {component.get('effective_weight')}"[:120])
    if chapters:
        y-=18; canvas.setFont("Helvetica-Bold",11); canvas.drawString(52,y,"AI-generated transcript-grounded chapters")
        for chapter in chapters: y-=14; canvas.setFont("Helvetica",8); canvas.drawString(60,y,f"{chapter.start_seconds:.1f}-{chapter.end_seconds:.1f}s {chapter.title}"[:110])
    if content:
        y-=18; canvas.setFont("Helvetica-Bold",11); canvas.drawString(52,y,"AI/deterministically generated content")
        for item in content: y-=14; canvas.setFont("Helvetica",8); canvas.drawString(60,y,f"{item.content_type}: {(item.edited_text or item.text)}"[:110])
    canvas.save()
    return path


def create_transcript_export(db: Session, session_id: int, format: str) -> Path | None:
    format=format.lower()
    if format not in {"json","csv","txt"}: raise ValueError("Transcript format must be json, csv, or txt")
    rows=db.scalars(select(models.TranscriptSegment).where(models.TranscriptSegment.session_id==session_id).order_by(models.TranscriptSegment.start_seconds)).all()
    if not rows: return None
    path=get_settings().report_dir/f"transcript_{session_id}.{format}"
    records=[{"id":r.id,"start_seconds":r.start_seconds,"end_seconds":r.end_seconds,"speaker_role":r.speaker_role,"text":r.corrected_text or r.original_text,"original_text":r.original_text,"correction_status":"HUMAN_CORRECTED" if r.corrected_text else "MACHINE_GENERATED","confidence":r.confidence,"provider":r.provider,"model_version":r.model_version} for r in rows]
    if format=="json": path.write_text(json.dumps({"session_id":session_id,"identity":"anonymous","segments":records},indent=2),encoding="utf-8")
    elif format=="txt": path.write_text("\n".join(f"[{r['start_seconds']:.3f}-{r['end_seconds']:.3f}] {r['speaker_role']} ({r['correction_status']}, confidence={r['confidence']}): {r['text']}" for r in records),encoding="utf-8")
    else:
        with path.open("w",newline="",encoding="utf-8") as stream: writer=csv.DictWriter(stream,fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    return path
