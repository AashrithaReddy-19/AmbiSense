import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AnalyticsSnapshot, Event
from ..crud import session_summary


def create_csv_report(db: Session, session_id: int) -> Path:
    rows = db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.session_id == session_id).order_by(AnalyticsSnapshot.timestamp)).all()
    path = get_settings().report_dir / f"session_{session_id}.csv"
    fields = ["timestamp", "student_count", "attendance", "attention_score", "engagement_score", "fatigue_score", "drowsiness_count", "yawning_count", "raised_hands", "distracted_students", "looking_down_students", "looking_away_students", "occupied_seats", "empty_seats", "noise_level"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: getattr(row, field) for field in fields} for row in rows])
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
    events = db.scalars(select(Event).where(Event.session_id == session_id).limit(12)).all()
    if events and y > 100:
        y -= 24; canvas.setFont("Helvetica-Bold", 11); canvas.drawString(52, y, "Important events")
        for event in events:
            y -= 14; canvas.setFont("Helvetica", 8); canvas.drawString(60, y, f"{event.timestamp:.1f}s - {event.event_type}: {event.message}"[:100])
    y -= 24; canvas.setFont("Helvetica-Bold", 10); canvas.drawString(52, max(70, y), "Methodology and privacy")
    canvas.setFont("Helvetica", 7); canvas.drawString(52, max(58, y - 12), "Anonymous YOLO tracking; landmark-derived head pose, EAR/MAR and pose participation. No face identity or face crops are stored.")
    canvas.setFont("Helvetica-Oblique", 8)
    canvas.drawString(52, 42, "Analytics are estimates for educational research, not medical or pedagogical diagnoses.")
    canvas.save()
    return path
