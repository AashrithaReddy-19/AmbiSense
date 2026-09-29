# Testing

```powershell
python -m pytest tests/ -q                       # backend
npm.cmd --prefix frontend test -- --run          # frontend (Vitest + React Testing Library, jsdom)
npm.cmd --prefix frontend run lint               # ESLint, zero warnings allowed
npm.cmd --prefix frontend run build              # type-check (tsc -b) + production build
python -m compileall -q backend scripts          # syntax check
python -m alembic heads; python -m alembic current
```

## Isolation (important)

`tests/conftest.py` runs **before** any application module is imported and points `DATABASE_URL`, `UPLOAD_DIR`,
`REPORT_DIR`, `LOG_DIR` and `CLASSROOM_REFERENCE_DIR` at throw-away locations under the system temp directory, and it
clears in-memory rate-limit counters before every test. The suite therefore never reads or writes `ambisense.db`,
`videos/` or `reports/`. Do not run tests with those variables overridden back to real paths.

Tests that change global settings must restore them (use `monkeypatch`), and must call `get_settings()` at use time: one
migration test clears the settings cache, which produces a new instance.

## What is covered

| Area | Where |
|---|---|
| Metric contract, trends, comparison, event counts | `test_metric_availability.py`, `test_comparison_and_trends.py`, `test_dashboard_overview.py` |
| Sessions/Reports/Search filters, RBAC, data-source separation, bounds | `test_phase3c_filters_and_search.py`, `test_search_sessions.py` |
| Error contract, request IDs, readiness, diagnostics, configuration validation, rate limiting, upload security | `test_hardening.py` |
| Jobs (atomic claim, idempotent retry, duplicate reports, recovery), deletion/retention/artifacts, no orphans | `test_jobs_retention.py` |
| Layout validation, management RBAC, settings, notifications, notes, audio capability, trends coverage | `test_phase3d_management.py` |
| Query counts (no N+1) | `test_query_efficiency.py` |
| Evaluation framework | `test_evaluation.py` |
| Database initialisation and migrations | `test_init_database.py`, `test_priority4_migration.py` |
| Upload → process → report → search workflow (deterministic tiny video) | `test_workflow.py`, `test_upload_config_and_live_frame_quality.py` |
| Timezone-aware time helpers, cleanup/startup that never rewrites history, stale-job preview and recovery | `test_phase4_hardening.py` |
| Artifact audit (report-only, path traversal, referenced/unknown files, deletion rules) | `test_artifact_audit.py` |
| Frontend pages, components, hooks, utilities | `frontend/src/**/*.test.ts(x)` |

## Real-browser check (optional, not part of `pytest`)

`scripts/browser_check.py` drives a local Chrome or Edge through the DevTools Protocol (needs only the `websockets` package;
nothing is downloaded). It audits every page at 360/768/1024/1440 px in light, dark and system themes (overflow, bad text,
unlabeled controls, chart alternatives, contrast, tap targets, console errors, failed requests, screenshots) and exercises
keyboard tabs, dialog focus, the mobile drawer, reduced motion and the loading/empty/error/unauthorized states.

**Run it against an isolated stack only** (a copy of the data and temporary upload/report folders on other ports), never the
database you care about: it opens dialogs and intercepts API calls.

```powershell
python scripts\browser_check.py --url http://127.0.0.1:5273 --backend http://127.0.0.1:8100 --out browser_report.json --shots shots
```

`--live` also drives the Live page with Chrome's **fake** camera device (a synthetic pattern, not a physical webcam).

## Artifact and orphan audits (read-only)

```powershell
python scripts\audit_artifacts.py                       # every file under videos\ and reports\, classified
python scripts\repair_orphan_notifications.py            # notifications pointing at deleted sessions (report only)
```

`audit_artifacts.py` deletes nothing unless you pass explicit file paths **and** `--apply`, and refuses anything a database
row references, anything outside the managed folders, directories, wildcards and symbolic links.

### Quarantining old automated-test artifacts (reversible, nothing is deleted)

```powershell
python scripts\quarantine_artifacts.py                        # dry run: what would move, with the proof for each file
python scripts\quarantine_artifacts.py --apply                # move to backups\quarantine_artifacts_<timestamp>\ + manifest.json
python scripts\quarantine_artifacts.py --restore <manifest> --apply   # put every file back
```

A file moves only if no database row references it **and** it is proven to be an automated-test artifact: named for a session
that a recorded cleanup run deleted whose recorded name is a test fixture ("API test", "Acceptance session", "Priority 3 …"),
or an upload that decodes as a tiny, perfectly uniform synthetic clip (the tests generate 160×90 solid-colour frames). Everything
else (referenced files, unknown files, unreferenced files that cannot be proven) stays where it is. The manifest stores each
file's original path, size, modified time, SHA-256 and proof; restore refuses to overwrite, to leave the managed folders or to
accept a file whose checksum changed.

### Repairing historical foreign-key violations

`scripts\repair_orphan_notifications.py` (report-only by default) lists notifications whose `session_id` points at a session
that no longer exists. `--apply` sets exactly those `session_id` values to NULL (no row is deleted, valid references are not
touched) and writes one `ORPHAN_NOTIFICATIONS_REPAIRED` audit entry. Stop the backend and take a backup first; the rollback is
copying that backup over `ambisense.db`.

Fixtures use small synthetic videos generated in the test (a few frames of a solid colour), never real footage, and no
physical webcam is needed.

## Not covered by automation

- Pixel-level rendering, real browsers and physical cameras (see the manual checklist in [DEMO_GUIDE.md](DEMO_GUIDE.md)).
- Detection accuracy on real classrooms ([EVALUATION.md](EVALUATION.md)).
- Container image builds and a live Redis.
