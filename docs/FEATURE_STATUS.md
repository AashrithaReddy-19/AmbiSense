# Feature status

Labels used everywhere in this project:

| Label | Meaning |
|---|---|
| **Implemented and tested** | Works and is covered by automated tests |
| **Implemented but optional** | Works when enabled/configured; not needed for the core flow |
| **Partially implemented** | Some of it works; the gap is stated |
| **Disabled by default** | Present, but off until an operator turns it on |
| **Planned** | Not built |
| **Legacy/deprecated** | Old code kept only for reference |
| **Not validated** | Runs, but its accuracy has not been measured on real classroom footage |

> Every detection-based indicator below is **Not validated** on real classroom footage. "Implemented and tested"
> means the software behaves as specified, not that the estimates are accurate.

## Analytics and evidence

| Capability | Status |
|---|---|
| Person detection + anonymous session-local tracking (YOLOv8 + ByteTrack) | Implemented and tested (software behaviour); **Not validated** (accuracy) |
| Anonymous occupancy estimate, peak occupancy, unoccupied capacity | Implemented and tested; **Not validated** |
| Visual-orientation estimate, possible fatigue, possible prolonged eye closure, yawning, raised-hand observations | Implemented and tested; **Not validated** |
| Metric availability contract (value, available, reason, coverage, confidence, valid/total observations) | Implemented and tested |
| Frame/camera quality assessment | Implemented and tested |
| Video upload → background processing → annotated video + CSV/PDF/metrics reports | Implemented and tested (deterministic synthetic video) |
| Live browser-camera analysis over WebSocket | Implemented; automated tests use mocked frames. Real-camera behaviour depends on the browser/camera and is not part of automated verification |
| Demo mode (synthetic, clearly labelled DEMO data) | Implemented and tested; **Disabled by default** |
| Classroom layouts (normalized polygons, versions, region aggregates, region heat maps) | Implemented and tested |
| Optional audio quality, transcription adapter, anonymous speaker roles, discourse, lecture content, evidence fusion | Implemented but optional; **Disabled by default**; transcription needs an installed provider; no diarization model is bundled |
| Emotion detection, identity recognition, verified attendance | **Not implemented, by design** |

## Application pages

| Page | Status |
|---|---|
| Overview dashboard | Implemented and tested |
| Live classroom | Implemented (see live-camera note above) |
| Upload & Processing | Implemented and tested |
| Sessions (search, status/classroom/course/activity/data-source filters, start/end date, minimum coverage, URL sync, archive) | Implemented and tested |
| Session Details tabs (Overview, Timeline, Quality & Evidence, Regions, Artifacts, Notes; `?tab=`, arrow-key navigation) | Implemented and tested |
| Analytics (metric/classroom/course/activity/data-source/period/date/coverage/confidence filters, chart gaps, 10-column evidence table, all states) | Implemented and tested |
| Compare 2–5 sessions (grouped/coverage/confidence/valid-observation/event-frequency charts, compatibility notices, accessible tables, CSV export, region comparison only for identical layouts) | Implemented and tested |
| Reports (search + 9 filters, pagination, details drawer, format-aware disabled actions, duplicate-download guard, safe retry) | Implemented and tested |
| Search (allowlisted session filters, metric thresholds, transcript text; explicit applied/not-applied filters) | Implemented and tested. Semantic (Sentence-BERT) matching is optional and used only as a fallback for metric intent |
| Notifications (read/unread, dismiss, category, severity, pagination, bulk read, deep links, de-duplication) | Implemented and tested |
| Classroom Setup (draw/edit polygons, validation, undo/redo, zoom/pan, keyboard control, versions, unsaved-change guard, confirmations) | Implemented and tested |
| Management (users, roles, courses, memberships, session assignment, classrooms, access matrix) | Implemented and tested |
| Settings (nine groups, ranges/units, restart flags, read-only environment values, confirmation for risky changes, audit) | Implemented and tested |

## Security, privacy and operations

| Capability | Status |
|---|---|
| Token authentication + role-based access control on HTTP and WebSocket | Implemented and tested; **auth is disabled by default** (development), with a visible warning |
| Consistent error contract with request IDs and safe structured logging | Implemented and tested |
| Startup configuration validation (fails safely with the setting name) | Implemented and tested |
| `/api/health` (lightweight), `/api/ready` (database, models, storage, job runner), `/api/v1/system/diagnostics` (admin, no secrets or paths) | Implemented and tested |
| Upload validation (extension, MIME, decode, size, duration, empty file, sanitised names, random storage names, cleanup after failure) | Implemented and tested |
| Rate limiting (login, upload, search, analytics, report) | Implemented and tested with the in-memory backend; the Redis backend is **Partially implemented**: code exists, not exercised against a live Redis |
| Job runner: atomic claim, idempotent retry, duplicate-report prevention, explicit stale-job recovery | Implemented and tested for the in-process runner. A durable queue runner is **Planned** (interface only) |
| Retention: archive by age (reversible), permanent session deletion, artifact deletion, audit trail, no orphaned rows or files | Implemented and tested |
| Startup never rewrites history; scheduled cleanup is opt-in; manual cleanup has a read-only preview and needs confirmation | Implemented and tested |
| Stale-session preview, Stale badge/banner, administrator-only confirmed recovery with audit (video jobs only; live captures reported, never changed) | Implemented and tested. The in-process runner is still not durable |
| Artifact audit (`scripts/audit_artifacts.py`: report-only classification of `videos\` and `reports\`; deletion only by explicit paths plus `--apply`) | Implemented and tested |
| Orphan-notification repair (`scripts/repair_orphan_notifications.py`) | Implemented and tested; **not applied to the real database** (needs approval) |
| Real-browser audit (`scripts/browser_check.py`, Chrome DevTools Protocol) | Implemented; run against an isolated copy of the data. Not part of `pytest` |
| Ethical evaluation framework (manifest, consent guard, split separation, metrics, CLI) | Implemented and tested on synthetic inputs. **No real evaluation has been run** |
| Docker/Nginx/PostgreSQL deployment files | Implemented; `docker compose config` validates; images not built in the verification environment |
| SSO / OIDC | **Planned** (not built) |
| Durable queue workers (Celery/RQ), object storage | **Planned** |
| Legacy Flask/DeepFace prototype (`app.py`, `face_processing.py`, `fire.py`, `noice.py`, `projector.py`, `temp.py`) | **Legacy/deprecated** |
