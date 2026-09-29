# Implementation status

The authoritative, labelled feature list is **[docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md)** (Implemented and tested / Implemented but optional / Partially implemented / Disabled by default / Planned / Legacy-deprecated / Not validated).

## Phases

| Phase | Scope | State |
|---|---|---|
| 1 | Audit | Complete |
| 2 | Correctness: isolated tests, dependency pins, test-pollution clean-up, Alembic backfill, metric-availability contract, canonical trends and comparison | Complete |
| 3A | Design system, responsive shell, themes, Overview | Complete |
| 3B | Live, Upload, Sessions, Session Details, toasts, breadcrumbs | Complete |
| 3C | Analytics, Compare, Reports, Search, Session tabs, Sessions date/coverage filters, accessible chart tables, bundle splitting | Complete |
| 3D | Classroom Setup, Management, Settings, Notifications, notes, audio capabilities, privacy/explainability, evaluation framework | Complete |
| Hardening | Error contract and request IDs, configuration validation, readiness/diagnostics, rate limiting, upload security, job-runner guarantees, retention and deletion, N+1 removal, Docker/Nginx | Complete (see limitations) |

## Known limitations

- **Not validated on real classroom footage.** No accuracy or fairness result exists.
- The in-process job runner is not durable; a queue runner is an interface only.
- The Redis rate-limit adapter and the container images were not exercised in the latest verification (no Redis server, no running Docker daemon).
- Physical-webcam capture and real-browser rendering were not part of automated verification (manual checklist in [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md)).
- SSO/OIDC, object storage and durable workers are planned, not built.
- Legacy Flask/DeepFace files are deprecated and untouched apart from a deprecation notice.

Exact verification commands and results for the latest run are in the final phase report; run the commands in [docs/TESTING.md](docs/TESTING.md) to reproduce them.
