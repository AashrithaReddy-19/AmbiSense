DEFAULT_WEIGHTS = {"attention": 0.45, "orientation": 0.20, "eye_state": 0.15, "activity": 0.10, "expression": 0.10}


def calculate_engagement(signals: dict[str, float], weights: dict[str, float] | None = None) -> dict[str, float | str]:
    selected = weights or DEFAULT_WEIGHTS
    total = sum(selected.values())
    if total <= 0:
        raise ValueError("Engagement weights must have a positive sum")
    score = sum(max(0.0, min(100.0, signals.get(name, 50.0))) * weight for name, weight in selected.items()) / total
    level = "LOW" if score < 40 else "MEDIUM" if score < 70 else "HIGH"
    return {"engagement_score": round(score, 2), "level": level, "name": "Estimated Engagement Index"}


def calculate_fatigue(drowsiness: float, yawning: float, looking_down: float, engagement_decline: float) -> dict[str, float | str]:
    score = 0.4 * drowsiness + 0.25 * yawning + 0.2 * looking_down + 0.15 * engagement_decline
    score = max(0.0, min(100.0, score))
    level = "LOW" if score < 35 else "MEDIUM" if score < 65 else "HIGH"
    return {"fatigue_score": round(score, 2), "level": level}
