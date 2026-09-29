# Development setup

## Windows (PowerShell)

Requirements: Python 3.11+ (developed on 3.13), Node.js 20+ (developed on 22).

```powershell
Copy-Item .env.example .env                       # optional
python -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend install
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

or `.\start_all.ps1` / `.\stop_all.ps1` (picks free ports, never kills other processes, logs to `logs\`).
The dev server proxies `/api` and `/ws` to `VITE_BACKEND_URL` (default `http://127.0.0.1:8000`).

Linux/macOS: `uvicorn backend.app.main:app --reload --port 8000` and `npm --prefix frontend run dev`.

Camera capture in the browser works on `http://localhost` and `https://` origins only.

## Environment variables

[.env.example](../.env.example) lists every variable with comments. Highlights:

| Area | Variables |
|---|---|
| Database | `DATABASE_URL` (SQLite file or `postgresql+psycopg://…`) |
| Storage | `UPLOAD_DIR`, `REPORT_DIR`, `LOG_DIR`, `CLASSROOM_REFERENCE_DIR`, `MAX_UPLOAD_MB`, `MAX_VIDEO_DURATION_MINUTES` |
| Network | `CORS_ORIGINS` (explicit origins; `*` rejected), `TRUSTED_HOSTS` |
| Auth | `AUTH_ENABLED`, `AUTH_MODE` (`TOKEN`/`DEVELOPMENT`), `AUTH_SECRET_KEY` (32+ chars in TOKEN mode) |
| Limits | `RATE_LIMIT_ENABLED`, `RATE_LIMIT_BACKEND` (`memory`/`redis`), `REDIS_URL`, `RATE_LIMIT_*_PER_MINUTE` |
| Processing | `JOB_RUNNER_MODE`, `DEMO_MODE`, `YOLO_MODEL`, thresholds |
| Retention | `RETENTION_DAYS`, `TRANSCRIPT_RETENTION_*`, `SCHEDULED_CLEANUP_ENABLED`, `TEST_SESSION_CLEANUP_*` |

**Starting the API never changes existing sessions.** The background cleanup loop is **off by default**
(`SCHEDULED_CLEANUP_ENABLED=false`, `TEST_SESSION_CLEANUP_ENABLED=false`). A production deployment can opt in by setting
`SCHEDULED_CLEANUP_ENABLED=true`; its first run happens one interval (`TEST_SESSION_CLEANUP_INTERVAL_MINUTES`) after start,
and a scheduled run that finds nothing writes no audit row. The one-off name-based test-session flagging only runs when a
legacy database first gains the `is_test` column. To clean up by hand, preview first
(`GET /api/v1/system/cleanup-test-sessions/preview`), then confirm
(`POST /api/v1/system/cleanup-test-sessions?confirm=true`); transcript retention likewise needs `confirm=true`.

**Start-up validation.** The API checks these settings when it starts and refuses to run, printing the setting name and
a fix, if for example the database URL scheme is unsupported, an origin is malformed or `*`, `AUTH_SECRET_KEY` is too
short in TOKEN mode, a storage directory is not writable, a numeric limit is out of range, or `JOB_RUNNER_MODE=QUEUE`
(no adapter is bundled). Warnings (auth disabled, DEVELOPMENT auth mode, missing optional models) are logged and shown in diagnostics.

## Database

New database: `python scripts/init_database.py` (creates the schema and stamps Alembic at head; `--dry-run` reports only).
Existing database with migration history: `python -m alembic upgrade head`. A legacy database that has tables but no
history is refused untouched: see [DEPLOYMENT.md](../DEPLOYMENT.md#alembic-stamping-for-legacy-databases).

## Code map

```
backend/app/main.py            routes, WebSockets, middleware wiring
backend/app/errors.py          error contract + request IDs
backend/app/auth.py            tokens, roles, session access (bulk_accessible_sessions avoids N+1)
backend/app/services/          jobs, retention, layout_validation, rate_limit, startup_checks, settings_catalog,
                               audio_capabilities, semantic_search, report_generator, video_processor, priority4 (analytics)
backend/app/evaluation/        ethical evaluation framework
frontend/src/pages/            route pages;  components/  shared UI (Tabs, Dialog, States, PrivacyNotice…)
frontend/src/hooks/            useUrlFilters, useRemoteList, useUndoRedo, useUnsavedChangesGuard
```

## Conventions worth knowing

- Filters that users can share live in the URL (`useUrlFilters`); Apply/Reset update it in **one** navigation.
- Anything destructive uses `ConfirmDialog` (typed phrase for permanent deletion) and a server-side `confirm=true` flag.
- Never render an unavailable metric as `0`; use `MetricValue` / `formatMetricAvailability`.
- Do not use `<aside>` for page content: the app shell styles every `<aside>` as the fixed navigation.
