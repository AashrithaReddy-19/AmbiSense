from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from . import models
from .metrics import frame_quality_metric


def session_summary(db: DBSession, session_id: int) -> dict:
    session = db.get(models.Session, session_id)
    if not session:
        raise LookupError("Session not found")
    rows = db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id == session_id).order_by(models.AnalyticsSnapshot.timestamp)).all()
    quality_rows = db.scalars(select(models.QualityAssessment).where(models.QualityAssessment.session_id == session_id)).all()
    hand_events = db.scalar(select(func.count(models.Event.id)).where(models.Event.session_id == session_id, models.Event.event_type == "HAND_RAISED")) or 0
    return _summarize(session, rows, quality_rows, hand_events)


def batch_session_summaries(db: DBSession, sessions: list[models.Session]) -> dict[int, dict]:
    """Summaries for many sessions using three queries in total (snapshots, quality, hand events),
    instead of three queries per session. Output is identical to ``session_summary``."""
    ids = [session.id for session in sessions]
    if not ids:
        return {}
    snapshots: dict[int, list] = {i: [] for i in ids}
    for row in db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id.in_(ids)).order_by(models.AnalyticsSnapshot.session_id, models.AnalyticsSnapshot.timestamp)).all():
        snapshots[row.session_id].append(row)
    quality: dict[int, list] = {i: [] for i in ids}
    for row in db.scalars(select(models.QualityAssessment).where(models.QualityAssessment.session_id.in_(ids))).all():
        quality[row.session_id].append(row)
    hands = dict(db.execute(select(models.Event.session_id, func.count(models.Event.id)).where(models.Event.session_id.in_(ids), models.Event.event_type == "HAND_RAISED").group_by(models.Event.session_id)).all())
    return {session.id: _summarize(session, snapshots[session.id], quality[session.id], hands.get(session.id, 0)) for session in sessions}


def _summarize(session: models.Session, rows: list, quality_rows: list, hand_events: int) -> dict:
    from .services.priority4 import _session_metric_results  # deferred: avoids a services -> crud import cycle at module load

    session_id = session.id
    quality_scores = [r.overall_quality for r in quality_rows if r.overall_quality is not None]
    quality_overall = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None
    quality_warnings = sorted({w for r in quality_rows for w in (r.details or {}).get("warnings", [])})
    metric_results = _session_metric_results(rows)
    metric_results["frame_quality"] = frame_quality_metric(quality_rows, quality_overall, quality_warnings)
    if not rows:
        return {"session_id": session_id, "status": session.status, "snapshots": 0, "metric_results": metric_results}
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
        "total_participation_events": hand_events,
        "average_occupancy": average("occupied_seats"),
        "recommendations": build_recommendations(rows),
        "metric_results": metric_results,
    }


def build_recommendations(rows: list[models.AnalyticsSnapshot]) -> list[str]:
    messages = []
    if len(rows) > 2 and rows[-1].engagement_score + 10 < rows[0].engagement_score:
        messages.append("The observable participation indicator declined toward the end of the session.")
    if sum(row.attention_score for row in rows) / len(rows) >= 70:
        messages.append("The average visual-orientation estimate remained above 70%.")
    if rows[-1].fatigue_score > rows[0].fatigue_score + 10:
        messages.append("Possible fatigue indicators increased during the session.")
    peak_hand = max(rows, key=lambda row: row.raised_hands)
    if peak_hand.raised_hands:
        messages.append(f"Raised-hand observations peaked at {peak_hand.timestamp:.1f} seconds ({peak_hand.raised_hands} observed).")
    average_occupancy = sum(row.occupied_seats for row in rows) / len(rows)
    messages.append(f"Average anonymous occupancy estimate was {average_occupancy:.1f} people.")
    return messages or ["No notable trend crossed the configured thresholds."]
