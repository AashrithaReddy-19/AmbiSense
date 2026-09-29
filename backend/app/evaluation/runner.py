"""Evaluation runner: validates a dataset manifest, then computes metrics for tasks that have labels."""
import hashlib
import json
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from . import NO_RESULTS_NOTICE, NOT_VALIDATED_NOTICE
from .metrics import angular_error, average_precision, binary_event_metrics, id_switches, mae_rmse, runtime_metrics

EVENT_TASKS = ("raised_hand", "yawn", "prolonged_eye_closure")
ALL_TASKS = ("occupancy", "detection", *EVENT_TASKS, "head_pose", "tracking", "runtime")


class DatasetManifest(BaseModel):
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    source: str = Field(min_length=1, description="Where the footage came from.")
    consent_statement: str = Field(min_length=10, description="How consent/approval was obtained.")
    consent_verified: bool
    approved_by: str = Field(min_length=1)
    splits: dict[str, list[str]] = Field(description="Item IDs per split: train, validation, test.")


class RunConfig(BaseModel):
    model_version: str = Field(min_length=1)
    threshold_version: str = Field(min_length=1)
    configuration_snapshot: dict = Field(default_factory=dict)


class EvaluationError(ValueError):
    pass


def validate_manifest(manifest: DatasetManifest) -> None:
    if not manifest.consent_verified:
        raise EvaluationError("Consent has not been verified for this dataset; evaluation refused.")
    seen: dict[str, str] = {}
    for split, ids in manifest.splits.items():
        for item in ids:
            if item in seen and seen[item] != split:
                raise EvaluationError(f"Item '{item}' appears in both '{seen[item]}' and '{split}'; splits must be disjoint.")
            seen[item] = split
    if not manifest.splits.get("test"):
        raise EvaluationError("A non-empty 'test' split is required.")


def _by_item(rows: list[dict] | None) -> dict:
    return {row["item_id"]: row for row in rows or []}


def evaluate(manifest: DatasetManifest, config: RunConfig, ground_truth: dict, predictions: dict, split: str = "test") -> dict:
    validate_manifest(manifest)
    allowed = set(manifest.splits.get(split, []))
    if not allowed:
        raise EvaluationError(f"Split '{split}' is empty or undefined.")
    results: dict[str, dict] = {}

    truth_occupancy, predicted_occupancy = _by_item(ground_truth.get("occupancy")), _by_item(predictions.get("occupancy"))
    pairs = [(float(truth_occupancy[i]["value"]), float(predicted_occupancy[i]["value"])) for i in sorted(allowed) if i in truth_occupancy and i in predicted_occupancy]
    if pairs:
        results["occupancy"] = mae_rmse(pairs)

    truth_boxes, predicted_boxes = _by_item(ground_truth.get("detections")), _by_item(predictions.get("detections"))
    detection_items = [{"truth": truth_boxes[i]["boxes"], "predicted": predicted_boxes.get(i, {}).get("boxes", [])} for i in sorted(allowed) if i in truth_boxes]
    if detection_items:
        aps = [average_precision(detection_items, 0.5 + 0.05 * step)["ap"] for step in range(10)]
        valid = [ap for ap in aps if ap is not None]
        results["detection"] = {"ap50": aps[0], "map_50_95": sum(valid) / len(valid) if valid else None, "samples": len(detection_items), "ground_truth_boxes": sum(len(item["truth"]) for item in detection_items)}

    for task in EVENT_TASKS:
        truth_events, predicted_events = _by_item((ground_truth.get("events") or {}).get(task)), _by_item((predictions.get("events") or {}).get(task))
        pairs_bool = [(bool(truth_events[i]["present"]), bool(predicted_events[i]["present"])) for i in sorted(allowed) if i in truth_events and i in predicted_events]
        if pairs_bool:
            results[task] = binary_event_metrics(pairs_bool)

    truth_pose, predicted_pose = _by_item(ground_truth.get("head_pose")), _by_item(predictions.get("head_pose"))
    common = [i for i in sorted(allowed) if i in truth_pose and i in predicted_pose]
    if common:
        results["head_pose"] = {
            "yaw": angular_error([(float(truth_pose[i]["yaw"]), float(predicted_pose[i]["yaw"])) for i in common]),
            "pitch": angular_error([(float(truth_pose[i]["pitch"]), float(predicted_pose[i]["pitch"])) for i in common]),
        }

    sequences = [s["predicted_ids"] for s in (predictions.get("tracking") or {}).get("sequences", []) if s.get("item_id") is None or s.get("item_id") in allowed]
    if sequences:
        results["tracking"] = id_switches(sequences)
    if predictions.get("runtime"):
        results["runtime"] = runtime_metrics(predictions["runtime"])

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split": split,
        "dataset": {"dataset_id": manifest.dataset_id, "version": manifest.version, "source": manifest.source, "consent_verified": True, "approved_by": manifest.approved_by, "split_sizes": {k: len(v) for k, v in manifest.splits.items()}},
        "model_version": config.model_version,
        "threshold_version": config.threshold_version,
        "configuration_hash": hashlib.sha256(json.dumps(config.configuration_snapshot, sort_keys=True, default=str).encode()).hexdigest(),
        "configuration_snapshot": config.configuration_snapshot,
        "metrics": results,
        "not_evaluated": [name for name in ALL_TASKS if name not in results],
        "fairness": "NOT_EVALUATED",
        "limitations": [
            f"Metrics describe only the supplied '{split}' split of dataset '{manifest.dataset_id}' v{manifest.version}.",
            "Results do not generalise beyond the labelled data." if results else NOT_VALIDATED_NOTICE,
            "No fairness analysis was performed." if results else NO_RESULTS_NOTICE,
        ],
    }
