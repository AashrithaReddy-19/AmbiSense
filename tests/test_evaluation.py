"""Evaluation framework: metrics on tiny SYNTHETIC inputs (never real footage),
consent/split guards, the CLI, and the honest not-validated status."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.evaluation import NO_RESULTS_NOTICE, NOT_VALIDATED_NOTICE
from backend.app.evaluation.metrics import angular_error, average_precision, binary_event_metrics, id_switches, iou, mae_rmse, percentile, precision_recall_f1, runtime_metrics
from backend.app.evaluation.runner import DatasetManifest, EvaluationError, RunConfig, evaluate
from backend.app.main import app

ROOT = Path(__file__).resolve().parents[1]


def _manifest(**overrides):
    values = dict(dataset_id="synthetic-unit-test", version="1", source="synthetic fixtures generated in the test", consent_statement="Synthetic data; no people are depicted.", consent_verified=True, approved_by="test-suite", splits={"train": ["t1"], "validation": ["v1"], "test": ["a", "b", "c", "d"]})
    values.update(overrides)
    return DatasetManifest(**values)


CONFIG = RunConfig(model_version="model-1", threshold_version="thresholds-1", configuration_snapshot={"ear_threshold": 0.21})


def test_precision_recall_f1_and_undefined_values_are_none_not_zero():
    metrics = precision_recall_f1(8, 2, 8)
    assert metrics["precision"] == pytest.approx(0.8) and metrics["recall"] == pytest.approx(0.5) and metrics["f1"] == pytest.approx(2 * 0.8 * 0.5 / 1.3)
    none = precision_recall_f1(0, 0, 0)
    assert none["precision"] is None and none["recall"] is None and none["f1"] is None


def test_binary_event_metrics():
    result = binary_event_metrics([(True, True), (True, False), (False, True), (False, False)])
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (1, 1, 1)
    assert result["f1"] == pytest.approx(0.5) and result["samples"] == 4


def test_mae_rmse():
    result = mae_rmse([(10, 12), (20, 17), (5, 5)])
    assert result["mae"] == pytest.approx(5 / 3) and result["rmse"] == pytest.approx(((4 + 9 + 0) / 3) ** 0.5)
    assert mae_rmse([]) == {"mae": None, "rmse": None, "samples": 0}


def test_iou_and_average_precision():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    perfect = [{"truth": [(0, 0, 10, 10)], "predicted": [{"box": (0, 0, 10, 10), "score": 0.9}]}]
    assert average_precision(perfect)["ap"] == pytest.approx(1.0)
    missed = [{"truth": [(0, 0, 10, 10)], "predicted": []}]
    assert average_precision(missed)["ap"] == 0.0
    assert average_precision([{"truth": [], "predicted": []}])["ap"] is None
    half = [{"truth": [(0, 0, 10, 10), (50, 50, 60, 60)], "predicted": [{"box": (0, 0, 10, 10), "score": 0.9}]}]
    assert average_precision(half)["ap"] == pytest.approx(0.5)


def test_id_switches_head_pose_percentiles_and_runtime():
    assert id_switches([[1, 1, 2, 2, 3], [7, 7, 7], [4, None, 5]])["id_switches"] == 3
    assert angular_error([(0, 5), (10, 5)])["mean_absolute_error_degrees"] == 5
    assert percentile([10, 20, 30, 40], 0.5) == 25
    runtime = runtime_metrics({"latencies_ms": [10, 20, 30], "frames": 30, "seconds": 3, "attempts": 10, "failures": 1, "coverage": {"valid": 8, "total": 10}})
    assert runtime["fps"] == 10 and runtime["failure_rate"] == 0.1 and runtime["coverage"] == 0.8 and runtime["latency_ms_p50"] == 20


def test_consent_and_split_guards():
    with pytest.raises(EvaluationError, match="Consent"):
        evaluate(_manifest(consent_verified=False), CONFIG, {}, {})
    with pytest.raises(EvaluationError, match="disjoint"):
        evaluate(_manifest(splits={"train": ["a"], "test": ["a"]}), CONFIG, {}, {})
    with pytest.raises(EvaluationError, match="test"):
        evaluate(_manifest(splits={"train": ["a"]}), CONFIG, {}, {})
    with pytest.raises(EvaluationError, match="empty or undefined"):
        evaluate(_manifest(), CONFIG, {}, {}, split="holdout")


def test_evaluate_uses_only_the_requested_split_and_reports_what_was_not_evaluated():
    truth = {"occupancy": [{"item_id": "a", "value": 10}, {"item_id": "b", "value": 20}, {"item_id": "t1", "value": 99}],
             "events": {"yawn": [{"item_id": "a", "present": True}, {"item_id": "b", "present": False}, {"item_id": "c", "present": True}]},
             "head_pose": [{"item_id": "a", "yaw": 0, "pitch": 0}]}
    predicted = {"occupancy": [{"item_id": "a", "value": 12}, {"item_id": "b", "value": 20}, {"item_id": "t1", "value": 0}],
                 "events": {"yawn": [{"item_id": "a", "present": True}, {"item_id": "b", "present": True}, {"item_id": "c", "present": False}]},
                 "head_pose": [{"item_id": "a", "yaw": 4, "pitch": 6}],
                 "tracking": {"sequences": [{"predicted_ids": [1, 1, 2]}]}}
    report = evaluate(_manifest(), CONFIG, truth, predicted)
    assert report["metrics"]["occupancy"]["samples"] == 2 and report["metrics"]["occupancy"]["mae"] == 1  # the train item t1 is excluded
    assert report["metrics"]["yawn"]["true_positive"] == 1 and report["metrics"]["yawn"]["false_positive"] == 1 and report["metrics"]["yawn"]["false_negative"] == 1
    assert report["metrics"]["head_pose"]["yaw"]["mean_absolute_error_degrees"] == 4
    assert report["metrics"]["tracking"]["id_switches"] == 1
    assert {"detection", "raised_hand", "prolonged_eye_closure", "runtime"} <= set(report["not_evaluated"])
    assert report["fairness"] == "NOT_EVALUATED"
    assert report["dataset"]["dataset_id"] == "synthetic-unit-test" and report["model_version"] == "model-1" and report["threshold_version"] == "thresholds-1"
    assert len(report["configuration_hash"]) == 64 and report["configuration_snapshot"] == {"ear_threshold": 0.21}
    assert any("does not generalise" in text or "Results do not generalise" in text for text in report["limitations"])


def test_report_without_any_labels_states_it_is_not_validated():
    report = evaluate(_manifest(), CONFIG, {}, {})
    assert report["metrics"] == {} and NOT_VALIDATED_NOTICE in report["limitations"] and NO_RESULTS_NOTICE in report["limitations"]


def test_status_endpoint_states_no_validation_exists():
    with TestClient(app) as client:
        body = client.get("/api/v1/evaluation/status").json()
    assert body["validated"] is False and body["headline"] == "Not validated on real classroom footage."
    assert body["detail"] == "No verified accuracy or fairness result is currently available."
    assert body["fairness"] == "NOT_EVALUATED"


def test_cli_refuses_unverified_consent_and_runs_on_verified_data(tmp_path):
    def write(name, content):
        path = tmp_path / name
        path.write_text(json.dumps(content), encoding="utf-8")
        return str(path)

    config = write("run.json", {"model_version": "m", "threshold_version": "t"})
    truth = write("truth.json", {"occupancy": [{"item_id": "a", "value": 5}]})
    predictions = write("pred.json", {"occupancy": [{"item_id": "a", "value": 6}]})
    good = write("good.json", _manifest(splits={"test": ["a"]}).model_dump())
    bad = write("bad.json", _manifest(consent_verified=False, splits={"test": ["a"]}).model_dump())
    run = lambda manifest: subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate.py"), "--manifest", manifest, "--config", config, "--ground-truth", truth, "--predictions", predictions], capture_output=True, text=True, cwd=ROOT)
    refused = run(bad)
    assert refused.returncode == 2 and "Consent" in refused.stderr
    accepted = run(good)
    assert accepted.returncode == 0 and json.loads(accepted.stdout)["metrics"]["occupancy"]["mae"] == 1
