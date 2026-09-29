# Evaluation framework

> **Current status: not validated on real classroom footage. No verified accuracy or fairness result is currently
> available.** The framework below is ready to *produce* such results from consented, labelled data. It ships no dataset
> and reports nothing until you supply one. The application shows this statement in Settings, reports and the API
> (`GET /api/v1/evaluation/status`).

## Principles

1. **Consent first.** A dataset manifest must state how consent/approval was obtained and set `consent_verified: true`; otherwise evaluation refuses to run.
2. **Separate splits.** `train`, `validation` and `test` item IDs must be disjoint, and a non-empty `test` split is required. Metrics are computed only on the split you name (default `test`).
3. **Reproducibility.** Every report records the dataset ID/version, model version, threshold version and a hash of the configuration snapshot.
4. **Honesty.** A task with no labels is listed under `not_evaluated`; fairness is always `NOT_EVALUATED` (the framework does not perform subgroup analysis). Metrics describe the supplied split only and do not generalise.
5. **No persistence surprises.** Nothing is written to the application database; no migration is required. Reports are JSON files you keep.

## Files

```
backend/app/evaluation/metrics.py   pure metric functions
backend/app/evaluation/runner.py    manifest/config models, validation, evaluate()
scripts/evaluate.py                 command-line runner
```

### Dataset manifest (`manifest.json`)

```json
{ "dataset_id": "pilot-classroom", "version": "2026-10-01", "description": "…", "source": "Recorded with written consent of …",
  "consent_statement": "Written consent obtained from instructor and students; approved by …", "consent_verified": true,
  "approved_by": "Institutional review contact", "splits": { "train": ["c1"], "validation": ["c2"], "test": ["c3", "c4"] } }
```

### Run configuration (`run.json`)

```json
{ "model_version": "yolov8n + mediapipe-face-landmarker", "threshold_version": "thresholds-1",
  "configuration_snapshot": { "ear_threshold": 0.21, "yawn_threshold": 0.6 } }
```

### Ground truth and predictions (`truth.json`, `predictions.json`)

Both use the same shapes; only tasks present in *both* are evaluated.

```json
{ "occupancy":  [{ "item_id": "c3", "value": 12 }],
  "detections": [{ "item_id": "c3", "boxes": [[10, 10, 50, 90]] }],             // predictions: [{"box":[…],"score":0.9}]
  "events": { "raised_hand": [{ "item_id": "c3", "present": true }], "yawn": [], "prolonged_eye_closure": [] },
  "head_pose": [{ "item_id": "c3", "yaw": 5.0, "pitch": -2.0 }],
  "tracking":  { "sequences": [{ "predicted_ids": [1, 1, 2] }] },              // predictions only
  "runtime":   { "latencies_ms": [120, 130], "frames": 300, "seconds": 30, "attempts": 10, "failures": 0, "coverage": { "valid": 8, "total": 10 } } }
```

```powershell
python scripts\evaluate.py --manifest manifest.json --config run.json --ground-truth truth.json --predictions predictions.json --out report.json
```

Exit code `2` means the run was refused (missing consent, overlapping splits, empty split) with the reason on stderr.

## Metrics computed

| Task | Metrics |
|---|---|
| Person detection | AP@0.5 and mAP@0.5:0.95 (all-point interpolation) |
| Occupancy | MAE, RMSE |
| Tracking | Identity switches along ground-truth sequences |
| Raised hand, yawn, prolonged eye closure | Precision, recall, F1 (`null`, not 0, when undefined) |
| Head pose | Mean absolute error of yaw and pitch (degrees) |
| Runtime | Latency mean/p50/p95, FPS, failure rate, evidence coverage |

## Before you trust a result

Collect footage only with consent and an approved purpose; label it with more than one annotator where possible;
keep the test split untouched while tuning; report results per camera setup and lighting condition; and analyse
subgroup performance separately (not provided here). Until then, treat every AmbiSense indicator as **unvalidated**.
