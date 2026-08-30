"""Validated, explainable metric envelopes shared by APIs and processors."""
from __future__ import annotations

import math
from enum import StrEnum
from typing import Any


class MetricStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MODEL_DISABLED = "MODEL_DISABLED"
    MODEL_LOADING = "MODEL_LOADING"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"


def bounded_percentage(value: Any) -> float | None:
    """Return a finite 0..100 percentage, or None when no valid value exists."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(max(0.0, min(100.0, number)), 2)


def safe_rate(numerator: Any, denominator: Any) -> float | None:
    try:
        top, bottom = float(numerator), float(denominator)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(top) or not math.isfinite(bottom) or bottom <= 0:
        return None
    return bounded_percentage(top / bottom * 100)


def metric_envelope(
    name: str,
    value: Any,
    *,
    valid_observations: int = 0,
    eligible_observations: int = 0,
    confidence: float | None = None,
    limitations: list[str] | None = None,
    model_enabled: bool = True,
    minimum_coverage: float = 0.2,
    unit: str = "percent",
) -> dict[str, Any]:
    valid = max(0, int(valid_observations))
    eligible = max(0, int(eligible_observations))
    coverage = safe_rate(valid, eligible)
    bounded = bounded_percentage(value) if unit == "percent" else value
    if not model_enabled:
        status = MetricStatus.MODEL_DISABLED
        bounded = None
    elif eligible == 0:
        status = MetricStatus.UNAVAILABLE
        bounded = None
    elif valid == 0 or coverage is None or coverage < minimum_coverage * 100:
        status = MetricStatus.INSUFFICIENT_EVIDENCE
        bounded = None
    elif bounded is None:
        status = MetricStatus.UNAVAILABLE
    else:
        status = MetricStatus.AVAILABLE
    confidence_value = bounded_percentage((confidence if confidence is not None else (coverage or 0) / 100) * 100)
    label = "Insufficient evidence" if status != MetricStatus.AVAILABLE else "High" if (confidence_value or 0) >= 80 else "Medium" if (confidence_value or 0) >= 50 else "Low"
    reasons = {
        MetricStatus.MODEL_DISABLED: "model_disabled",
        MetricStatus.INSUFFICIENT_EVIDENCE: "insufficient_valid_observations",
        MetricStatus.UNAVAILABLE: "required_evidence_unavailable",
    }
    if eligible == 0 and name in {"visual_orientation", "possible_fatigue", "prolonged_eye_closure", "yawning"}:
        reason = "no_detectable_person"
    elif valid == 0 and eligible > 0 and name in {"visual_orientation", "possible_fatigue", "prolonged_eye_closure", "yawning"}:
        reason = "facial_landmarks_unavailable"
    else:
        reason = None if status == MetricStatus.AVAILABLE else reasons.get(status, status.value.lower())
    return {
        "metric": name, "value": bounded, "unit": unit, "status": status.value,
        "available": status == MetricStatus.AVAILABLE, "reason": reason,
        "confidence": None if confidence_value is None else round(confidence_value / 100, 3),
        "confidence_label": label,
        "coverage": {"valid_observations": valid, "eligible_observations": eligible, "ratio": round((coverage or 0) / 100, 3)},
        "limitations": limitations or [],
    }
