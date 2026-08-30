# Model Evaluation

The application exposes model availability at `/api/models/health` and session camera-quality evidence at `/api/v1/sessions/{id}/quality`. Priority 1 tests cover metric bounds, missing evidence, occupancy math, track lifecycle/deduplication, quality assessment, state transitions, API workflow, and demo/real labeling.

Dataset precision, recall, calibration, fairness slices, and privacy-safe error review are not yet implemented. They remain Priority 5 work and must not be inferred from model availability.
