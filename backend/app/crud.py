from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from . import models


def session_summary(db: DBSession, session_id: int) -> dict:
    session = db.get(models.Session, session_id)
    if not session:
        raise LookupError("Session not found")
    rows = db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id == session_id).order_by(models.AnalyticsSnapshot.timestamp)).all()
    if not rows:
        return {"session_id": session_id, "status": session.status, "snapshots": 0}
    average = lambda field: round(sum(float(getattr(row, field)) for row in rows) / len(rows), 2)
    engagement = [row.engagement_score for row in rows]
    return {
        "session_id": session_id, "status": session.status, "snapshots": len(rows),
        "duration_seconds": round(rows[-1].timestamp, 2), "average_occupancy_rate": round(sum(row.occupancy_rate or 0 for row in rows) / len(rows), 2), "verified_attendance_rate": None,
        "average_engagement": average("engagement_score"), "peak_engagement": round(max(engagement), 2),
        "lowest_engagement": round(min(engagement), 2), "average_attention": average("attention_score"),
        "average_fatigue": average("fatigue_score"), "total_yawns": max(row.yawning_count for row in rows),
        "peak_students": max(row.student_count for row in rows), "average_students": average("student_count"),
        "minimum_students": min(row.student_count for row in rows), "peak_raised_hands": max(row.raised_hands for row in rows),
        "total_participation_events": sum(1 for row in db.scalars(select(models.Event).where(models.Event.session_id == session_id, models.Event.event_type == "HAND_RAISED"))),
        "average_occupancy": average("occupied_seats"),
        "recommendations": build_recommendations(rows),
    }


def build_recommendations(rows: list[models.AnalyticsSnapshot]) -> list[str]:
    messages = []
    if len(rows) > 2 and rows[-1].engagement_score + 10 < rows[0].engagement_score:
        messages.append("Estimated engagement declined toward the end of the session.")
    if sum(row.attention_score for row in rows) / len(rows) >= 70:
        messages.append("Average visual attention estimate remained above 70%.")
    if rows[-1].fatigue_score > rows[0].fatigue_score + 10:
        messages.append("Possible fatigue indicators increased during the session.")
    peak_hand = max(rows, key=lambda row: row.raised_hands)
    if peak_hand.raised_hands:
        messages.append(f"Participation peaked at {peak_hand.timestamp:.1f} seconds with {peak_hand.raised_hands} raised hand(s).")
    average_occupancy = sum(row.occupied_seats for row in rows) / len(rows)
    messages.append(f"Average anonymous occupancy was {average_occupancy:.1f} students.")
    return messages or ["No notable trend crossed the configured thresholds."]
