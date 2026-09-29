"""Tests for the canonical MetricAvailability contract: schema validation
rules, the metric_envelope/build_metric constructors, and its integration
into the quality REST endpoint, the live WebSocket, and CSV/PDF reports."""
import csv
import io

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.main import app
from backend.app.metrics import as_metric_availability, build_metric, metric_envelope
from backend.app.schemas import MetricAvailability
from backend.app.services.report_generator import create_metrics_csv_report, create_pdf_report, metric_availability_rows


# --- Schema validation rules -------------------------------------------------

def test_available_non_zero_value():
    m = MetricAvailability(value=73.5, available=True, coverage=0.9, confidence=0.8, valid_observations=9, total_observations=10)
    assert m.value == 73.5 and m.available is True and m.reason is None


def test_available_zero_value_is_not_unavailable():
    m = MetricAvailability(value=0, available=True, coverage=1.0, valid_observations=1, total_observations=1)
    assert m.value == 0
    assert m.available is True


def test_unavailable_null_value():
    m = MetricAvailability(value=None, available=False, reason="no_observations")
    assert m.value is None and m.available is False


def test_unavailable_requires_reason():
    with pytest.raises(ValidationError):
        MetricAvailability(value=None, available=False)


def test_available_requires_non_null_value():
    with pytest.raises(ValidationError):
        MetricAvailability(value=None, available=True)


def test_unavailable_cannot_carry_a_fabricated_value():
    with pytest.raises(ValidationError):
        MetricAvailability(value=42, available=False, reason="no_observations")


def test_coverage_boundary_validation():
    MetricAvailability(value=1, available=True, coverage=0.0)
    MetricAvailability(value=1, available=True, coverage=1.0)
    with pytest.raises(ValidationError):
        MetricAvailability(value=1, available=True, coverage=1.1)
    with pytest.raises(ValidationError):
        MetricAvailability(value=1, available=True, coverage=-0.1)


def test_confidence_boundary_validation():
    MetricAvailability(value=1, available=True, confidence=0.0)
    MetricAvailability(value=1, available=True, confidence=1.0)
    with pytest.raises(ValidationError):
        MetricAvailability(value=1, available=True, confidence=1.5)


def test_valid_observations_cannot_exceed_total():
    with pytest.raises(ValidationError):
        MetricAvailability(value=1, available=True, valid_observations=5, total_observations=2)


def test_observation_counts_cannot_be_negative():
    with pytest.raises(ValidationError):
        MetricAvailability(value=1, available=True, valid_observations=-1)
    with pytest.raises(ValidationError):
        MetricAvailability(value=1, available=True, total_observations=-1)


def test_unknown_reason_code_rejected():
    with pytest.raises(ValidationError):
        MetricAvailability(value=None, available=False, reason="made_up_reason")


# --- metric_envelope / build_metric reason selection -------------------------

def test_insufficient_observations_reason():
    result = build_metric(80, valid_observations=1, total_observations=10, minimum_observations=3)
    assert result["available"] is False
    assert result["reason"] == "insufficient_valid_observations"
    MetricAvailability(**result)


def test_zero_total_observations_reason():
    result = build_metric(None, valid_observations=0, total_observations=0)
    assert result["reason"] == "no_observations"
    assert result["coverage"] is None
    MetricAvailability(**result)


def test_coverage_calculation():
    result = build_metric(50, valid_observations=4, total_observations=8, minimum_coverage=0.1)
    assert result["coverage"] == 0.5
    assert result["available"] is True


def test_poor_quality_frame_reason():
    result = build_metric(None, valid_observations=5, total_observations=5, failure_reason="poor_frame_quality")
    assert result["reason"] == "poor_frame_quality"
    assert result["value"] is None
    MetricAvailability(**result)


def test_missing_face_landmarks_reason():
    result = build_metric(None, valid_observations=0, total_observations=4, required_evidence="facial_landmarks")
    assert result["reason"] == "facial_landmarks_unavailable"


def test_missing_pose_landmarks_reason():
    result = build_metric(None, valid_observations=0, total_observations=4, required_evidence="pose_landmarks")
    assert result["reason"] == "pose_landmarks_unavailable"


def test_context_inapplicable_metric():
    result = build_metric(80, valid_observations=5, total_observations=5, activity_applicable=False)
    assert result["available"] is False
    assert result["reason"] == "not_applicable_for_activity"
    assert result["value"] is None


def test_legacy_data_without_evidence():
    from backend.app.metrics import LEGACY_METRIC
    MetricAvailability(**LEGACY_METRIC)
    assert LEGACY_METRIC["reason"] == "legacy_data_without_evidence"
    assert LEGACY_METRIC["value"] is None


def test_as_metric_availability_adapts_pre_contract_nested_coverage_shape():
    # Snapshots persisted before this checkpoint stored `coverage` as a
    # nested {valid_observations, eligible_observations, ratio} object with
    # no top-level valid/total_observations keys. That is real evidence, not
    # missing evidence, so it must be re-projected onto the canonical flat
    # shape rather than treated as legacy_data_without_evidence.
    legacy_shaped_envelope = {
        "metric": "visual_orientation", "value": 21.23, "unit": "percent", "status": "AVAILABLE",
        "available": True, "reason": None, "confidence": 0.25, "confidence_label": "Low",
        "coverage": {"valid_observations": 1, "eligible_observations": 4, "ratio": 0.25},
        "limitations": [],
    }
    result = as_metric_availability(legacy_shaped_envelope)
    assert result == {
        "value": 21.23, "available": True, "reason": None, "coverage": 0.25,
        "confidence": 0.25, "valid_observations": 1, "total_observations": 4,
    }
    MetricAvailability(**result)


def test_metric_envelope_output_validates_against_canonical_schema():
    for envelope in (
        metric_envelope("occupancy", 0, valid_observations=1, eligible_observations=1, unit="count"),
        metric_envelope("visual_orientation", None, valid_observations=0, eligible_observations=0),
        metric_envelope("visual_orientation", None, valid_observations=0, eligible_observations=5),
        metric_envelope("raised_hands", None, valid_observations=0, eligible_observations=3, unit="count"),
        metric_envelope("possible_fatigue", 40, valid_observations=0, eligible_observations=0, model_enabled=False),
    ):
        MetricAvailability(**as_metric_availability(envelope))


# --- REST integration ---------------------------------------------------------

def test_quality_endpoint_returns_canonical_frame_quality_field():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"name": "quality contract test", "is_test": True}).json()["id"]
        body = client.get(f"/api/v1/sessions/{session_id}/quality").json()
        assert body["frame_quality"]["available"] is False
        assert body["frame_quality"]["reason"] == "no_observations"
        MetricAvailability(**body["frame_quality"])


# --- WebSocket integration -----------------------------------------------------

def test_live_websocket_metrics_are_strictly_canonical():
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"name": "ws canonical contract", "source_type": "LIVE", "is_test": True}).json()
        ok, jpeg = cv2.imencode(".jpg", np.zeros((240, 320, 3), dtype=np.uint8))
        assert ok
        with client.websocket_connect(f"/ws/live/{session['id']}") as socket:
            socket.receive_json()
            socket.send_bytes(jpeg.tobytes())
            update = socket.receive_json()
            for entry in update["metrics"].values():
                assert set(entry) == {"value", "available", "reason", "coverage", "confidence", "valid_observations", "total_observations"}
                MetricAvailability(**entry)
            socket.send_text("STOP")


# --- Report / CSV / PDF integration --------------------------------------------

def test_metric_availability_rows_use_legacy_reason_when_no_snapshot():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"name": "report contract test", "is_test": True}).json()["id"]
        from backend.app.database import SessionLocal
        with SessionLocal() as db:
            rows = metric_availability_rows(db, session_id)
        assert len(rows) == 9
        for row in rows:
            assert row["available"] is False
            assert row["reason"] == "legacy_data_without_evidence"
            MetricAvailability(**{k: row[k] for k in ("value", "available", "reason", "coverage", "confidence", "valid_observations", "total_observations")})


def test_metrics_csv_report_has_canonical_columns():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"name": "csv contract test", "is_test": True}).json()["id"]
        from backend.app.database import SessionLocal
        with SessionLocal() as db:
            path = create_metrics_csv_report(db, session_id)
        content = path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(content))
        assert reader.fieldnames == ["metric_name", "value", "available", "reason", "coverage", "confidence", "valid_observations", "total_observations"]
        rows = list(reader)
        assert len(rows) == 9
        assert all(row["reason"] == "legacy_data_without_evidence" for row in rows)


def test_pdf_report_generates_with_metric_availability_section():
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"name": "pdf contract test", "is_test": True}).json()["id"]
        from backend.app.database import SessionLocal
        with SessionLocal() as db:
            path = create_pdf_report(db, session_id)
        assert path.exists() and path.stat().st_size > 0


# --- Comparison excludes unavailable values, never treats them as zero --------

def test_comparison_excludes_unavailable_metrics_instead_of_zeroing_them():
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.database import Base
    from backend.app import models
    from backend.app.services.priority4 import compare

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        with_evidence = models.Session(name="Has evidence", status="COMPLETED", analytics_mode="REAL", created_at=datetime(2026, 8, 1), activity_context="LECTURE")
        without_evidence = models.Session(name="No evidence", status="COMPLETED", analytics_mode="REAL", created_at=datetime(2026, 8, 2), activity_context="LECTURE")
        db.add_all([with_evidence, without_evidence]); db.flush()
        envelope = metric_envelope("observable_participation", 64, valid_observations=10, eligible_observations=10)
        db.add(models.AnalyticsSnapshot(session_id=with_evidence.id, timestamp=0, student_count=10, engagement_score=64, details={"metrics": {"observable_participation": envelope}}))
        db.commit()
        result = compare(db, [with_evidence, without_evidence], ["observable_participation"])
        # The metric is available on at least one compared session, so the
        # comparison as a whole is not flagged unavailable - but the session
        # that genuinely lacks evidence must still report null, never 0.
        assert result["status"] == "AVAILABLE"
        rows_by_name = {row["name"]: row for row in result["sessions"]}
        assert rows_by_name["No evidence"]["metrics"].get("observable_participation") is None
        assert rows_by_name["Has evidence"]["metrics"].get("observable_participation") == 64.0

        # When NO compared session has the metric at all, it must be called
        # out explicitly rather than silently rendered as a column of zeros.
        both_missing = compare(db, [without_evidence], ["observable_participation"])
        assert both_missing["status"] == "INSUFFICIENT_EVIDENCE"
        assert any("not converted to zero" in warning for warning in both_missing["warnings"])
