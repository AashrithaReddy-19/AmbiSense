# Model evaluation

> **Not validated on real classroom footage. No verified accuracy or fairness result is currently available.**

What exists today:

- **Availability, not accuracy.** `GET /api/models/health` reports whether each model/library is present, and `GET /api/ready` fails when the required detector is missing. Presence says nothing about correctness.
- **Behavioural tests** on synthetic inputs (metric bounds, missing evidence, occupancy de-duplication, quality warnings, contract shapes). These check the *software*, not the *estimates*.
- **An evaluation framework** ([docs/EVALUATION.md](docs/EVALUATION.md)) that will compute detection AP/mAP, occupancy MAE/RMSE, tracking ID switches, raised-hand/yawn/prolonged-eye-closure precision/recall/F1, head-pose error, coverage, failure rate, latency and FPS from a **consented, approved, labelled** dataset, with disjoint train/validation/test splits, model/threshold versioning and a configuration hash. It has only been exercised on tiny synthetic inputs in unit tests.

What does **not** exist: any real dataset, any measured accuracy, any fairness or subgroup analysis, and calibration of
the confidence values. Until an evaluation has been run and reviewed, the interface and reports state that the
indicators are not validated, and they must not inform grading, discipline, attendance or other high-impact decisions.
