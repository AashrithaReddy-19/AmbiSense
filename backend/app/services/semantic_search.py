import logging
import re
from datetime import datetime, timedelta
from ..timeutil import as_naive_utc, utc_now_naive
from functools import lru_cache

import numpy as np
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..models import AnalyticsSnapshot, Classroom, GeneratedContentItem, QualityAssessment, Report, Session as ClassroomSession, TranscriptSegment


logger = logging.getLogger("ambisense.search")
METRICS = {
    "distracted": "distracted_students", "distraction": "distracted_students",
    "attendance": "occupancy_rate", "occupancy": "occupancy_rate",
    "engagement": "engagement_score", "attention": "attention_score",
    "fatigue": "fatigue_score", "drowsiness": "drowsiness_count",
    "yawn": "yawning_count", "raised hand": "raised_hands", "participation": "raised_hands",
    "looking down": "looking_down_students", "looking away": "looking_away_students",
}
INTENTS = {
    "distracted_students": "students whose head direction is away from the front of the room",
    "occupancy_rate": "anonymous occupancy presence room capacity",
    "engagement_score": "classroom engagement involvement",
    "attention_score": "visual attention looking toward instructor",
    "fatigue_score": "fatigue tiredness declining energy",
    "drowsiness_count": "possible drowsiness prolonged eye closure",
    "yawning_count": "yawning mouth opening",
    "raised_hands": "raised hands participation questions",
    "looking_down_students": "students looking down",
    "looking_away_students": "students looking away sideways",
}


@lru_cache(maxsize=1)
def _semantic_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def semantic_metric(query: str) -> tuple[str, float]:
    try:
        model = _semantic_model()
        labels = list(INTENTS)
        vectors = model.encode([query, *INTENTS.values()], normalize_embeddings=True)
        scores = vectors[1:] @ vectors[0]
        index = int(np.argmax(scores))
        return labels[index], float(scores[index])
    except Exception as error:
        logger.warning("Sentence-BERT fallback unavailable: %s", error)
        return "engagement_score", 0.0


def parse_query(query: str) -> dict[str, object]:
    text = query.lower().strip()
    direct = next(((word, field) for word, field in METRICS.items() if word in text), None)
    if direct:
        metric, confidence = direct[1], 1.0
    else:
        metric, confidence = semantic_metric(text)
    match = re.search(r"(\d+(?:\.\d+)?)\s*%?", text)
    value = float(match.group(1)) if match else None
    if any(word in text for word in ("below", "less than", "under", "lower than", "lowest", "minimum", "low")):
        operator = "<"
    elif any(word in text for word in ("above", "more than", "over", "greater than", "higher than", "at least", "highest", "maximum", "high")):
        operator = ">"
    else:
        operator = "min" if "when" in text else "max"
    session_match = re.search(r"session\s*#?\s*(\d+)", text)
    time_match = re.search(r"(?:after|from)\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds|m|min|minutes)?", text)
    return {"metric": metric, "operator": operator, "value": value, "session_id": int(session_match.group(1)) if session_match else None, "time_from": float(time_match.group(1)) if time_match else None, "confidence": round(confidence, 3), "parser": "deterministic" if direct else "sentence-bert"}


def search_analytics(db: Session, query: str) -> dict:
    text = query.lower().strip()
    session_match = re.search(r"session\s*#?\s*(\d+)", text)
    session_id = int(session_match.group(1)) if session_match else None
    # These are explicit, allowlisted read-only intents. User input is always bound
    # through SQLAlchemy and is never interpreted as SQL.
    if any(word in text for word in ("transcript", "said", "mention", "concept", "definition", "question")):
        words=[w for w in re.findall(r"[a-z0-9_-]{3,}",text) if w not in {"transcript","said","mention","mentioned","concept","definition","question","session"} and not w.isdigit()]
        statement=select(TranscriptSegment,ClassroomSession).join(ClassroomSession,ClassroomSession.id==TranscriptSegment.session_id)
        if session_id: statement=statement.where(TranscriptSegment.session_id==session_id)
        if words:
            clauses=[TranscriptSegment.original_text.ilike(f"%{w}%") for w in words]
            statement=statement.where(or_(*clauses))
        rows=db.execute(statement.order_by(TranscriptSegment.start_seconds).limit(100)).all()
        return {"query":query,"interpreted_filter":{"intent":"TRANSCRIPT_EVIDENCE","terms":words,"session_id":session_id,"parser":"deterministic_allowlist"},"applied_filters":[{"name":"transcript_terms","description":"Transcript text contains any of: "+", ".join(words)} if words else {"name":"transcript","description":"All stored transcript segments"}]+([{"name":"session_id","description":f"Session #{session_id}"}] if session_id else []),"not_applied":[],"match_kind":"TEXT_MATCH","matches":[{"session_id":r.session_id,"session":s.name,"timestamp":r.start_seconds,"metric":"transcript","value":r.corrected_text or r.original_text,"reason":"Transcript evidence at the cited timestamp","confidence":r.confidence,"evidence_segment_id":r.id} for r,s in rows]}
    if "poor camera" in text or "camera quality" in text:
        statement=select(QualityAssessment,ClassroomSession).join(ClassroomSession,ClassroomSession.id==QualityAssessment.session_id).where(QualityAssessment.status.in_(["POOR","LIMITED"]))
        if session_id: statement=statement.where(QualityAssessment.session_id==session_id)
        rows=db.execute(statement.order_by(QualityAssessment.timestamp).limit(100)).all()
        return {"query":query,"interpreted_filter":{"intent":"CAMERA_QUALITY","session_id":session_id,"parser":"deterministic_allowlist"},"applied_filters":[{"name":"camera_quality","description":"Stored frame-quality assessment is POOR or LIMITED"}]+([{"name":"session_id","description":f"Session #{session_id}"}] if session_id else []),"not_applied":[],"match_kind":"EXPLICIT_FILTERS","matches":[{"session_id":r.session_id,"session":s.name,"timestamp":r.timestamp,"metric":"camera_quality","value":r.status,"reason":"Stored frame-quality assessment","confidence":r.overall_quality} for r,s in rows]}
    if is_session_query(text):
        return search_sessions(db, query)
    parsed = parse_query(query)
    column = getattr(AnalyticsSnapshot, str(parsed["metric"]))
    statement = select(AnalyticsSnapshot, ClassroomSession).join(ClassroomSession, ClassroomSession.id == AnalyticsSnapshot.session_id)
    if parsed["value"] is not None:
        statement = statement.where(column < parsed["value"] if parsed["operator"] == "<" else column >= parsed["value"])
    if parsed["session_id"]:
        statement = statement.where(AnalyticsSnapshot.session_id == parsed["session_id"])
    if parsed["time_from"] is not None:
        statement = statement.where(AnalyticsSnapshot.timestamp >= parsed["time_from"])
    statement = statement.order_by(column.asc() if parsed["operator"] in ("<", "min") else column.desc()).limit(100)
    rows = db.execute(statement).all()
    matches = []
    for row, session in rows:
        value = getattr(row, str(parsed["metric"]))
        matches.append({"session_id": row.session_id, "session": session.name, "date": session.created_at, "timestamp": row.timestamp, "metric": parsed["metric"], "value": value, "reason": f"{parsed['metric'].replace('_', ' ')} was {value} at {row.timestamp:.1f}s", "confidence": parsed["confidence"]})
    applied = [{"name": "metric", "description": f"Metric is {str(parsed['metric']).replace('_', ' ')} (stored per-interval snapshot value)"}]
    if parsed["value"] is not None: applied.append({"name": "threshold", "description": f"Value {'is below' if parsed['operator'] == '<' else 'is at least'} {parsed['value']:g}"})
    if parsed["session_id"]: applied.append({"name": "session_id", "description": f"Session #{parsed['session_id']}"})
    if parsed["time_from"] is not None: applied.append({"name": "time_from", "description": f"At or after {parsed['time_from']:g} seconds into the session"})
    applied.append({"name": "ordering", "description": "Lowest values first" if parsed["operator"] in ("<", "min") else "Highest values first"})
    not_applied = []
    if any(word in text for word in ("last week", "yesterday", "today", "this week", "last month", "this month")): not_applied.append({"name": "date_range", "description": "Date phrases are only supported for session searches (for example 'completed sessions from last week')"})
    return {"query": query, "interpreted_filter": parsed, "applied_filters": applied, "not_applied": not_applied, "match_kind": "SEMANTIC_METRIC" if parsed.get("parser") == "sentence-bert" else "KEYWORD_METRIC", "matches": matches}


# ---------------------------------------------------------------------------
# Session-metadata search: explicit, allowlisted filters only (never free SQL).
# Every recognised filter is echoed back in ``applied_filters``; anything the
# parser noticed but cannot apply is listed in ``not_applied`` so the UI never
# claims a filter that did not run.
# ---------------------------------------------------------------------------
SESSION_TERMS = ("session", "job", "report", "failed", "completed", "processing", "queued", "coverage", "classroom", "lecture", "exam", "discussion", "laboratory", "presentation", "upload", "live recording", "recordings")
STATUS_WORDS = (("failed", ("FAILED",)), ("failure", ("FAILED",)), ("completed", ("COMPLETED",)), ("finished", ("COMPLETED",)), ("queued", ("QUEUED",)), ("stopped", ("STOPPED",)), ("processing", ("PROCESSING", "DECODING", "AGGREGATING", "GENERATING_REPORT", "INITIALIZING")))
ACTIVITY_WORDS = (("examination", "EXAMINATION"), ("exam", "EXAMINATION"), ("lecture", "LECTURE"), ("group discussion", "GROUP_DISCUSSION"), ("discussion", "GROUP_DISCUSSION"), ("laboratory", "LABORATORY"), ("lab ", "LABORATORY"), ("presentation", "STUDENT_PRESENTATION"), ("independent writing", "INDEPENDENT_WRITING"), ("reading", "READING"), ("video screening", "VIDEO_SCREENING"), ("break", "BREAK"))
LOW_COVERAGE_MAX, HIGH_COVERAGE_MIN = 0.5, 0.8  # same tier thresholds as the dashboard data-quality breakdown


def _has_metric_keyword(text: str) -> bool:
    return any(word in text for word in METRICS)


def is_session_query(text: str) -> bool:
    return not _has_metric_keyword(text) and any(term in text for term in SESSION_TERMS)


def _date_range(text: str, now: datetime) -> tuple[datetime | None, datetime | None, str | None]:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = midnight - timedelta(days=midnight.weekday())
    if "yesterday" in text:
        return midnight - timedelta(days=1), midnight, "yesterday (UTC)"
    if "today" in text:
        return midnight, now, "today (UTC)"
    if "last week" in text or "previous week" in text:
        return monday - timedelta(days=7), monday, "last week = the previous calendar week, Monday to Sunday (UTC)"
    if "this week" in text:
        return monday, now, "this week = since Monday (UTC)"
    first_of_month = midnight.replace(day=1)
    if "last month" in text or "previous month" in text:
        return (first_of_month - timedelta(days=1)).replace(day=1), first_of_month, "last month = the previous calendar month (UTC)"
    if "this month" in text:
        return first_of_month, now, "this month = since the 1st (UTC)"
    days = re.search(r"(?:last|past)\s+(\d{1,3})\s+days?", text)
    if days:
        return now - timedelta(days=int(days.group(1))), now, f"the last {int(days.group(1))} days"
    return None, None, None


def search_sessions(db: Session, query: str, now: datetime | None = None) -> dict:
    text = f" {query.lower().strip()} "
    now = as_naive_utc(now) if now else utc_now_naive()
    applied, not_applied, filters = [], [], {"intent": "SESSION_METADATA", "parser": "deterministic_allowlist"}
    statement = select(ClassroomSession).where(ClassroomSession.archived.is_(False))

    status = next((states for word, states in STATUS_WORDS if word in text), None)
    if status:
        statement = statement.where(ClassroomSession.status.in_(status)); filters["status"] = list(status)
        applied.append({"name": "status", "description": f"Status is {' / '.join(status).replace('_', ' ').lower()}"})
    activity = next((value for word, value in ACTIVITY_WORDS if word in text), None)
    if activity:
        statement = statement.where(ClassroomSession.activity_context == activity); filters["activity_context"] = activity
        applied.append({"name": "activity_context", "description": f"Activity context is {activity.replace('_', ' ').lower()}"})
    start, end, phrase = _date_range(text, now)
    if start:
        statement = statement.where(ClassroomSession.created_at >= start, ClassroomSession.created_at < end if end and end != now else ClassroomSession.created_at <= now)
        filters["date_from"], filters["date_to"] = start.isoformat(), (end or now).isoformat()
        applied.append({"name": "date_range", "description": f"Created {phrase}"})
    classroom_match = re.search(r"(?:classroom|room)\s+([a-z0-9][a-z0-9-]*)", text)
    if classroom_match:
        token = classroom_match.group(1)
        names = {row.id: row.name.lower() for row in db.execute(select(Classroom.id, Classroom.name)).all()}
        ids = [cid for cid, name in names.items() if name in {f"classroom {token}", f"room {token}", token}]
        filters["classroom"] = token
        if ids:
            statement = statement.where(ClassroomSession.classroom_id.in_(ids)); filters["classroom_ids"] = ids
            applied.append({"name": "classroom", "description": f"Classroom is {', '.join(sorted(names[i] for i in ids))}"})
        else:
            statement = statement.where(ClassroomSession.id == -1)
            applied.append({"name": "classroom", "description": f"Classroom '{token}' — no classroom has that name"})
    if re.search(r"\breports?\b", text):
        statement = statement.where(ClassroomSession.id.in_(select(Report.session_id))); filters["has_report"] = True
        applied.append({"name": "has_report", "description": "Has at least one generated report"})

    coverage_min = coverage_max = None
    coverage_words = "coverage" in text
    if coverage_words:
        number = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if number:
            threshold = float(number.group(1)) / 100
            if any(word in text for word in ("below", "under", "less than", "lower than", "low")): coverage_max = threshold
            else: coverage_min = threshold
        elif re.search(r"\blow\b|\bpoor\b|insufficient|\bweak\b", text): coverage_max = LOW_COVERAGE_MAX
        elif re.search(r"\bhigh\b|\bgood\b|\bstrong\b", text): coverage_min = HIGH_COVERAGE_MIN
        else: not_applied.append({"name": "coverage", "description": "Coverage was mentioned without a level such as 'low', 'high' or a percentage"})
    if len(applied) == 0 and coverage_min is None and coverage_max is None:
        not_applied.append({"name": "query", "description": "No supported session filter (status, activity, date range, classroom, reports, coverage) was recognised"})

    candidates = db.scalars(statement.order_by(ClassroomSession.created_at.desc())).all()
    ids = [row.id for row in candidates]
    coverage: dict[int, float] = {}
    if ids:
        for session_id, total, present in db.execute(select(AnalyticsSnapshot.session_id, func.count(), func.sum(case((AnalyticsSnapshot.student_count > 0, 1), else_=0))).where(AnalyticsSnapshot.session_id.in_(ids)).group_by(AnalyticsSnapshot.session_id)).all():
            if total: coverage[session_id] = (present or 0) / total
    if coverage_max is not None:
        filters["coverage_below"] = coverage_max
        # Sessions with no processed evidence at all count as low (insufficient) coverage.
        candidates = [row for row in candidates if coverage.get(row.id) is None or coverage[row.id] < coverage_max]
        applied.append({"name": "coverage", "description": f"Evidence coverage is below {round(coverage_max * 100)}% (or no processed evidence)"})
    if coverage_min is not None:
        filters["coverage_at_least"] = coverage_min
        candidates = [row for row in candidates if coverage.get(row.id) is not None and coverage[row.id] >= coverage_min]
        applied.append({"name": "coverage", "description": f"Evidence coverage is at least {round(coverage_min * 100)}%"})
    candidates = candidates[:100]
    with_reports = set(db.scalars(select(Report.session_id).where(Report.session_id.in_([row.id for row in candidates]))).all()) if candidates else set()
    room_names = {row.id: row.name for row in db.execute(select(Classroom.id, Classroom.name)).all()}
    matches = [{
        "session_id": row.id, "session": row.name, "date": row.created_at, "timestamp": None, "metric": "session", "value": row.status,
        "status": row.status, "activity_context": row.activity_context, "source_type": row.source_type, "classroom_id": row.classroom_id,
        "classroom_name": room_names.get(row.classroom_id), "coverage": None if row.id not in coverage else round(coverage[row.id], 3), "has_report": row.id in with_reports,
        "reason": "Matched because: " + "; ".join(item["description"] for item in applied if item["name"] != "query") if applied else "Matched the default session listing",
        "confidence": None,  # explicit filters, not a similarity score
    } for row in candidates]
    return {"query": query, "interpreted_filter": filters, "applied_filters": applied, "not_applied": not_applied, "match_kind": "EXPLICIT_FILTERS", "matches": matches}
