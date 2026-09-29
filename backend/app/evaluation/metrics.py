"""Pure metric functions; every function is deterministic and dependency-free."""
import math
from statistics import mean

Box = tuple[float, float, float, float]


def precision_recall_f1(true_positive: int, false_positive: int, false_negative: int) -> dict:
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else None
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "true_positive": true_positive, "false_positive": false_positive, "false_negative": false_negative}


def binary_event_metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """``pairs`` are (ground_truth_present, predicted_present) per labelled item."""
    tp = sum(1 for truth, predicted in pairs if truth and predicted)
    fp = sum(1 for truth, predicted in pairs if not truth and predicted)
    fn = sum(1 for truth, predicted in pairs if truth and not predicted)
    return {**precision_recall_f1(tp, fp, fn), "samples": len(pairs)}


def mae_rmse(pairs: list[tuple[float, float]]) -> dict:
    if not pairs:
        return {"mae": None, "rmse": None, "samples": 0}
    errors = [predicted - truth for truth, predicted in pairs]
    return {"mae": mean(abs(e) for e in errors), "rmse": math.sqrt(mean(e * e for e in errors)), "samples": len(pairs)}


def iou(a: Box, b: Box) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def average_precision(items: list[dict], iou_threshold: float = 0.5) -> dict:
    """All-point interpolated AP for one class.

    ``items``: [{"truth": [box, ...], "predicted": [{"box": box, "score": float}, ...]}]
    """
    total_truth = sum(len(item["truth"]) for item in items)
    if total_truth == 0:
        return {"ap": None, "samples": len(items), "iou_threshold": iou_threshold}
    detections = sorted(((p["score"], index, tuple(p["box"])) for index, item in enumerate(items) for p in item["predicted"]), key=lambda d: -d[0])
    matched: list[set[int]] = [set() for _ in items]
    flags = []
    for _score, index, box in detections:
        best, best_iou = None, iou_threshold
        for truth_index, truth_box in enumerate(items[index]["truth"]):
            if truth_index in matched[index]:
                continue
            overlap = iou(box, tuple(truth_box))
            if overlap >= best_iou:
                best, best_iou = truth_index, overlap
        if best is not None:
            matched[index].add(best)
            flags.append(1)
        else:
            flags.append(0)
    tp = fp = 0
    precisions, recalls = [], []
    for flag in flags:
        tp += flag
        fp += 1 - flag
        precisions.append(tp / (tp + fp))
        recalls.append(tp / total_truth)
    envelope = list(precisions)  # monotone precision envelope, then integrate over recall
    for i in range(len(envelope) - 2, -1, -1):
        envelope[i] = max(envelope[i], envelope[i + 1])
    ap, previous_recall = 0.0, 0.0
    for precision, recall in zip(envelope, recalls):
        ap += (recall - previous_recall) * precision
        previous_recall = recall
    return {"ap": ap, "samples": len(items), "iou_threshold": iou_threshold, "detections": len(detections), "ground_truth_boxes": total_truth}


def id_switches(sequences: list[list]) -> dict:
    """Count identity changes of the predicted track ID along each ground-truth identity's sequence."""
    switches = 0
    for sequence in sequences:
        assigned = [value for value in sequence if value is not None]
        switches += sum(1 for previous, current in zip(assigned, assigned[1:]) if previous != current)
    return {"id_switches": switches, "sequences": len(sequences), "frames": sum(len(s) for s in sequences)}


def angular_error(pairs: list[tuple[float, float]]) -> dict:
    """Mean absolute head-pose error in degrees for (truth, predicted) pairs."""
    if not pairs:
        return {"mean_absolute_error_degrees": None, "samples": 0}
    return {"mean_absolute_error_degrees": mean(abs(predicted - truth) for truth, predicted in pairs), "samples": len(pairs)}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def runtime_metrics(runtime: dict) -> dict:
    latencies = [float(v) for v in runtime.get("latencies_ms", [])]
    attempts, failures = int(runtime.get("attempts", 0)), int(runtime.get("failures", 0))
    seconds, frames = float(runtime.get("seconds", 0) or 0), int(runtime.get("frames", 0) or 0)
    coverage = runtime.get("coverage") or {}
    return {
        "latency_ms_mean": mean(latencies) if latencies else None,
        "latency_ms_p50": percentile(latencies, 0.5),
        "latency_ms_p95": percentile(latencies, 0.95),
        "fps": frames / seconds if seconds > 0 and frames else None,
        "failure_rate": failures / attempts if attempts else None,
        "coverage": coverage.get("valid", 0) / coverage["total"] if coverage.get("total") else None,
    }
