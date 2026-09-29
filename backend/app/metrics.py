"""Validated, explainable metric envelopes shared by APIs, the CV pipeline,
WebSocket messages, and reports.

Every metric in AmbiSense is represented with one canonical contract (see
MetricAvailability in schemas.py):

    {"value", "available", "reason", "coverage", "confidence",
     "valid_observations", "total_observations"}

`metric_envelope()` is the one place that decides availability/reason from
raw evidence counts; every metric-producing code path (video_processor,
live WebSocket, heatmaps, trend aggregation, reports) calls it instead of
recreating this logic. It returns the seven canonical fields plus a few
additional, non-contract fields (`metric`, `unit`, `status`,
`confidence_label`, `limitations`) that existing internal consumers
(activity-context limitations, the live pipeline-health UI) already rely on.
`as_metric_availability()` projects a result down to exactly the canonical
seven fields when a strict contract response is required (new REST fields,
CSV/PDF export, the live WebSocket `metrics` payload).
"""
from __future__ import annotations

import math
from enum import StrEnum
from typing import Any


# Stable, machine-readable reason codes. Any "reason" a metric envelope
# returns must be one of these, or None when the metric is available.
REASON_CODES = frozenset({
    "no_observations",
    "insufficient_valid_observations",
    "no_person_detected",
    "facial_landmarks_unavailable",
    "pose_landmarks_unavailable",
    "poor_frame_quality",
    "low_light",
    "excessive_blur",
    "face_occluded",
    "model_unavailable",
    "inference_failed",
    "not_applicable_for_activity",
    "processing_incomplete",
    "legacy_data_without_evidence",
})

# Canonical field set for the flat MetricAvailability contract (Part 2/7 of
# the metric-availability checkpoint). Kept as a tuple so ordering is stable
# wherever it is used to build plain dicts for JSON responses.
CANONICAL_FIELDS = (
    "value", "available", "reason", "coverage",
    "confidence", "valid_observations", "total_observations",
)

# Metrics that require a detected face / facial landmarks, versus a
# detected pose, to distinguish "no one was in frame" from "someone was in
# frame but the required landmarks could not be extracted" for the reason
# code. Anything not listed here is treated as a structural/count metric
# (occupancy, unoccupied_capacity, frame_quality, ...).
FACE_DEPENDENT_METRICS = frozenset({
    "visual_orientation", "possible_fatigue", "prolonged_eye_closure",
    "yawning", "observable_participation",
})
POSE_DEPENDENT_METRICS = frozenset({"raised_hands"})
PERSON_DEPENDENT_METRICS = FACE_DEPENDENT_METRICS | POSE_DEPENDENT_METRICS


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


def _reason_for_unavailable(
    name: str, *, model_enabled: bool, valid: int, eligible: int,
    coverage_ratio: float | None, minimum_coverage: float, computed_is_none: bool,
) -> str:
    if not model_enabled:
        return "not_applicable_for_activity"
    if eligible == 0:
        return "no_person_detected" if name in PERSON_DEPENDENT_METRICS else "no_observations"
    if valid == 0:
        if name in FACE_DEPENDENT_METRICS:
            return "facial_landmarks_unavailable"
        if name in POSE_DEPENDENT_METRICS:
            return "pose_landmarks_unavailable"
        return "insufficient_valid_observations"
    if coverage_ratio is None or coverage_ratio < minimum_coverage:
        return "insufficient_valid_observations"
    if computed_is_none:
        return "inference_failed"
    return "insufficient_valid_observations"


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
    """Build the canonical metric-availability contract for one metric.

    `eligible_observations` is the denominator (e.g. students in frame);
    `valid_observations` is how many of those produced usable evidence for
    this specific metric (e.g. had extractable face landmarks). Coverage is
    valid/eligible. A metric is only ever `available` when a real, non-null
    value was computed from at least one valid observation meeting the
    minimum-coverage threshold; otherwise value is always null and a
    canonical reason code explains why.
    """
    valid = max(0, int(valid_observations))
    eligible = max(0, int(eligible_observations))
    if valid > eligible:
        eligible = valid
    coverage_ratio = round(valid / eligible, 4) if eligible > 0 else None
    bounded = bounded_percentage(value) if unit == "percent" else value
    computed_is_none = bounded is None

    is_available = (
        model_enabled and eligible > 0 and valid > 0
        and coverage_ratio is not None and coverage_ratio >= minimum_coverage
        and not computed_is_none
    )
    if is_available:
        status = MetricStatus.AVAILABLE
        reason = None
    else:
        bounded = None
        reason = _reason_for_unavailable(
            name, model_enabled=model_enabled, valid=valid, eligible=eligible,
            coverage_ratio=coverage_ratio, minimum_coverage=minimum_coverage,
            computed_is_none=computed_is_none,
        )
        status = {
            "not_applicable_for_activity": MetricStatus.MODEL_DISABLED,
            "no_person_detected": MetricStatus.UNAVAILABLE,
            "no_observations": MetricStatus.UNAVAILABLE,
            "facial_landmarks_unavailable": MetricStatus.INSUFFICIENT_EVIDENCE,
            "pose_landmarks_unavailable": MetricStatus.INSUFFICIENT_EVIDENCE,
            "insufficient_valid_observations": MetricStatus.INSUFFICIENT_EVIDENCE,
            "inference_failed": MetricStatus.FAILED,
        }[reason]
        assert reason in REASON_CODES  # defensive: catch typos in the map above during tests

    confidence_ratio = None
    if is_available:
        base_confidence = confidence if confidence is not None else (coverage_ratio or 0.0)
        confidence_ratio = round(max(0.0, min(1.0, float(base_confidence))), 4)
    confidence_pct = None if confidence_ratio is None else confidence_ratio * 100
    label = (
        "Insufficient evidence" if not is_available
        else "High" if (confidence_pct or 0) >= 80 else "Medium" if (confidence_pct or 0) >= 50 else "Low"
    )
    return {
        # Canonical MetricAvailability fields:
        "value": bounded,
        "available": is_available,
        "reason": reason,
        "coverage": coverage_ratio,
        "confidence": confidence_ratio,
        "valid_observations": valid,
        "total_observations": eligible,
        # Additional fields kept for existing internal consumers (activity
        # context limitations text, the live pipeline-health UI's status
        # fallback). Not part of the canonical contract.
        "metric": name,
        "unit": unit,
        "status": status.value,
        "confidence_label": label,
        "limitations": limitations or [],
    }


def as_metric_availability(envelope: dict[str, Any]) -> dict[str, Any]:
    """Project a metric_envelope() result down to exactly the seven
    canonical MetricAvailability fields, for response boundaries (new REST
    fields, the live WebSocket `metrics` payload, CSV/PDF export) that must
    not leak the extra internal-only fields.

    Also adapts records persisted before this contract existed: those
    envelopes carry the same evidence (`coverage` was a nested
    {valid_observations, eligible_observations, ratio} object instead of a
    flat ratio) under different keys. That is real, previously computed
    evidence, so it is re-projected onto the new field names rather than
    discarded - only a snapshot missing a metric key entirely falls back to
    "legacy_data_without_evidence" (handled by the caller, not here).
    """
    coverage = envelope.get("coverage")
    if isinstance(coverage, dict):
        return {
            "value": envelope.get("value"),
            "available": bool(envelope.get("available")),
            "reason": envelope.get("reason"),
            "coverage": coverage.get("ratio"),
            "confidence": envelope.get("confidence"),
            "valid_observations": coverage.get("valid_observations", 0),
            "total_observations": coverage.get("eligible_observations", 0),
        }
    return {key: envelope.get(key) for key in CANONICAL_FIELDS}


def build_metric(
    value: Any,
    *,
    valid_observations: int,
    total_observations: int,
    minimum_observations: int = 1,
    minimum_coverage: float = 0.2,
    confidence: float | None = None,
    activity_applicable: bool = True,
    required_evidence: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """Central constructor for metrics that do not naturally fit the
    per-student `metric_envelope()` shape (frame quality, region-level
    aggregates, legacy-record derivation, trend/comparison points).

    `required_evidence` names what kind of evidence is missing when
    `valid_observations` is zero (e.g. "facial_landmarks",
    "pose_landmarks", "frame_quality"); it maps to a specific reason code.
    `failure_reason`, when given, overrides all other logic and must be one
    of REASON_CODES (e.g. "model_unavailable", "poor_frame_quality").
    """
    valid = max(0, int(valid_observations))
    total = max(0, int(total_observations))
    if valid > total:
        total = valid
    coverage_ratio = round(valid / total, 4) if total > 0 else None

    def unavailable(reason: str) -> dict[str, Any]:
        if reason not in REASON_CODES:
            raise ValueError(f"Unknown metric reason code: {reason}")
        return {
            "value": None, "available": False, "reason": reason,
            "coverage": coverage_ratio, "confidence": None,
            "valid_observations": valid, "total_observations": total,
        }

    if failure_reason is not None:
        return unavailable(failure_reason)
    if not activity_applicable:
        return unavailable("not_applicable_for_activity")
    if total == 0:
        return unavailable("no_observations")
    if valid == 0:
        evidence_reason = {
            "facial_landmarks": "facial_landmarks_unavailable",
            "pose_landmarks": "pose_landmarks_unavailable",
        }.get(required_evidence, "insufficient_valid_observations")
        return unavailable(evidence_reason)
    if valid < minimum_observations or (coverage_ratio or 0) < minimum_coverage:
        return unavailable("insufficient_valid_observations")
    if value is None:
        return unavailable("inference_failed")

    confidence_ratio = round(max(0.0, min(1.0, float(confidence))), 4) if confidence is not None else coverage_ratio
    return {
        "value": value, "available": True, "reason": None,
        "coverage": coverage_ratio, "confidence": confidence_ratio,
        "valid_observations": valid, "total_observations": total,
    }


def frame_quality_metric(rows, overall: float | None, warnings: list[str]) -> dict[str, Any]:
    """Canonical MetricAvailability for session-level frame quality, derived
    at read time from stored QualityAssessment rows. Never rewrites history;
    a session with zero recorded assessments is simply unavailable. Shared
    by the /quality REST endpoint and session comparison/trends so both
    surfaces report the same value from the same evidence."""
    total = len(rows)
    valid = sum(1 for row in rows if row.overall_quality is not None)
    if total == 0:
        return build_metric(None, valid_observations=0, total_observations=0)
    if overall is None:
        return build_metric(None, valid_observations=valid, total_observations=total, required_evidence="frame_quality")
    reason = None
    if overall < 40:
        joined = " ".join(warnings).lower()
        reason = "low_light" if "underexposed" in joined or "overexposed" in joined else "excessive_blur" if "blur" in joined else "poor_frame_quality"
    return build_metric(
        None if reason else overall, valid_observations=valid, total_observations=total,
        minimum_coverage=0.0, failure_reason=reason,
    )


LEGACY_METRIC = {
    "value": None, "available": False, "reason": "legacy_data_without_evidence",
    "coverage": None, "confidence": None, "valid_observations": 0, "total_observations": 0,
}
