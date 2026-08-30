import math

import numpy as np
import pytest

from backend.app.cv.quality import assess_frame_quality
from backend.app.cv.tracking import TrackLifecycleManager
from backend.app.metrics import bounded_percentage, metric_envelope, safe_rate
from backend.app.session_state import SessionState, transition


@pytest.mark.parametrize(("value", "expected"), [(-1, 0), (395, 100), (50, 50), (float("nan"), None), (float("inf"), None), ("bad", None), (None, None)])
def test_percentage_validation(value, expected):
    assert bounded_percentage(value) == expected


def test_safe_rate_missing_and_zero_denominator():
    assert safe_rate(None, 40) is None
    assert safe_rate(4, None) is None
    assert safe_rate(4, 0) is None
    assert safe_rate(4, 8) == 50


def test_metric_states_distinguish_zero_from_unavailable():
    available = metric_envelope("occupancy", 0, valid_observations=1, eligible_observations=1)
    unavailable = metric_envelope("orientation", None, valid_observations=0, eligible_observations=0)
    disabled = metric_envelope("audio", 20, valid_observations=1, eligible_observations=1, model_enabled=False)
    partial = metric_envelope("orientation", 50, valid_observations=1, eligible_observations=10, minimum_coverage=.2)
    assert available["status"] == "AVAILABLE" and available["value"] == 0
    assert unavailable["status"] == "UNAVAILABLE" and unavailable["value"] is None
    assert disabled["status"] == "MODEL_DISABLED"
    assert partial["status"] == "INSUFFICIENT_EVIDENCE"


def test_track_validity_expiry_and_reentry_deduplication():
    manager = TrackLifecycleManager(minimum_observations=2, minimum_duration=1, timeout=2, reentry_window=8, iou_gate=.5)
    first = manager.observe(1, 0, .9, [0, 0, 10, 10])
    manager.observe(1, 1.1, .9, [0, 0, 10, 10])
    assert manager.valid_unique_count() == 1
    manager.expire(4)
    assert not first.active and first.expiry_reason == "TRACK_TIMEOUT"
    reentry = manager.observe(99, 5, .8, [0, 0, 10, 10])
    assert reentry.uuid == first.uuid and manager.valid_unique_count() == 1


def test_camera_quality_has_components_and_warnings():
    dark = np.zeros((80, 120, 3), dtype=np.uint8)
    result = assess_frame_quality(dark, people=4, face_count=0, pose_count=1)
    assert 0 <= result["overall_quality"] <= 100
    assert result["status"] in {"GOOD", "LIMITED", "POOR"}
    assert any("underexposed" in warning for warning in result["warnings"])


def test_session_state_rejects_invalid_transition():
    row = type("Row", (), {"status": "CREATED", "processing_stage": "CREATED"})()
    transition(row, SessionState.UPLOADING)
    assert row.status == "UPLOADING"
    with pytest.raises(ValueError): transition(row, SessionState.COMPLETED)
