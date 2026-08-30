import logging
import re
from functools import lru_cache

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import AnalyticsSnapshot, GeneratedContentItem, QualityAssessment, Session as ClassroomSession, TranscriptSegment


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
    "distracted_students": "students distracted or not attentive",
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
        return {"query":query,"interpreted_filter":{"intent":"TRANSCRIPT_EVIDENCE","terms":words,"session_id":session_id,"parser":"deterministic_allowlist"},"matches":[{"session_id":r.session_id,"session":s.name,"timestamp":r.start_seconds,"metric":"transcript","value":r.corrected_text or r.original_text,"reason":"Transcript evidence at the cited timestamp","confidence":r.confidence,"evidence_segment_id":r.id} for r,s in rows]}
    if "poor camera" in text or "camera quality" in text:
        statement=select(QualityAssessment,ClassroomSession).join(ClassroomSession,ClassroomSession.id==QualityAssessment.session_id).where(QualityAssessment.status.in_(["POOR","LIMITED"]))
        if session_id: statement=statement.where(QualityAssessment.session_id==session_id)
        rows=db.execute(statement.order_by(QualityAssessment.timestamp).limit(100)).all()
        return {"query":query,"interpreted_filter":{"intent":"CAMERA_QUALITY","session_id":session_id,"parser":"deterministic_allowlist"},"matches":[{"session_id":r.session_id,"session":s.name,"timestamp":r.timestamp,"metric":"camera_quality","value":r.status,"reason":"Stored frame-quality assessment","confidence":r.overall_quality} for r,s in rows]}
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
    return {"query": query, "interpreted_filter": parsed, "matches": matches}
