# Deployment

Two supported shapes: **local single machine** (SQLite, in-process jobs) and **containers** (PostgreSQL, Nginx).
Neither is a durable, horizontally scalable production queue: see [docs/JOBS.md](docs/JOBS.md).

## Local

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). `.\start_all.ps1` starts the API and dashboard on free ports and writes logs to `logs\`.

## Containers

```powershell
Copy-Item .env.example .env        # then set POSTGRES_PASSWORD, and AUTH_* for anything shared
docker compose up --build          # PostgreSQL + API + dashboard
docker compose --profile redis up --build   # additionally start Redis
```

| Service | Details |
|---|---|
| `postgres` | `postgres:16-alpine`, named volume `postgres_data`, healthcheck (`pg_isready`), **no published port** |
| `backend` | Built from `backend/Dockerfile`: unprivileged user (uid 10001), copies only application code and `yolov8n.pt` (`.dockerignore` keeps databases, uploads, reports, backups and secrets out of the image), healthcheck on `/api/health`, runs `scripts/init_database.py` then uvicorn. Volumes `videos`, `reports`, `logs`; `./models` mounted read-only. API published on `127.0.0.1:8000`. |
| `frontend` | Built from `frontend/Dockerfile`: Vite build served by unprivileged Nginx on 8080 (published as `FRONTEND_PORT`, default 5173), healthcheck `/healthz`. Nginx proxies `/api/` (300 s timeouts, streamed uploads, 520 MB body limit) and `/ws/` (WebSocket upgrade, 1 h timeout), serves hashed assets with long-lived caching, falls back to `index.html` for client routes and sets `nosniff`, frame and referrer headers. |
| `redis` | Only with `--profile redis`. **The application uses Redis only if `RATE_LIMIT_BACKEND=redis` and `REDIS_URL` are set**; otherwise rate limiting is in-process and Redis does nothing. The Redis adapter has not been exercised against a live Redis in automated tests. |

Restart policy is `unless-stopped`; the backend waits for PostgreSQL to be healthy and the frontend for the backend.
Add `--build-arg INSTALL_FFMPEG=true` (compose: `INSTALL_FFMPEG=true`) only if you enable optional audio analysis.

Validate the files without a Docker daemon: `docker compose config -q`. **Image builds and `nginx -t` need a running Docker daemon and were not run in the latest verification environment.**

### Before exposing it to anyone else

1. Set `AUTH_ENABLED=true`, `AUTH_MODE=TOKEN`, and a random `AUTH_SECRET_KEY` (32+ characters), then create the first administrator. With authentication off, everyone is an administrator and the UI shows a warning.
2. Set a real `POSTGRES_PASSWORD`.
3. Set `CORS_ORIGINS` to your real dashboard origin(s) and `TRUSTED_HOSTS` to your host name(s).
4. Terminate HTTPS in front of Nginx (required for browser camera access off `localhost`).
5. Decide retention (`RETENTION_DAYS`, `TRANSCRIPT_RETENTION_DAYS`) and obtain consent for the footage you process.

## Migrations

The migration chain starts from an already-existing base schema, so `alembic upgrade head` on an **empty** database fails. Use:

```powershell
python scripts\init_database.py --dry-run     # report what would happen; changes nothing
python scripts\init_database.py               # empty DB: create schema + stamp head; stamped DB: upgrade head; legacy DB: refuse
```

**Migration dry run against your real database (safe: works on a copy):**

```powershell
python -c "import sqlite3;s=sqlite3.connect('file:ambisense.db?mode=ro',uri=True);d=sqlite3.connect('dry_runs/copy.db');s.backup(d)"
python scripts\init_database.py --database-url sqlite:///dry_runs/copy.db --dry-run
```

### Alembic stamping for legacy databases

A database created before Alembic has tables but no `alembic_version`. `init_database.py` refuses it, untouched, because
guessing a revision could skip or repeat migrations. To adopt one: (1) stop the application, (2) back it up
([docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md)), (3) work out which revision its schema matches (compare against
`migrations/versions/`; `20260920_backfill_legacy_constraints` is the current head), (4) `python -m alembic stamp <revision>`,
(5) `python -m alembic upgrade head`, (6) verify (`PRAGMA integrity_check; PRAGMA foreign_key_check;`). Rehearse on a copy first.

## Backup and restore

See [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md). Restore is deliberately manual and is never scripted to run automatically.

## Configuration checks at runtime

`GET /api/health` (liveness), `GET /api/ready` (database, models, storage, job runner; `503` when not ready),
`GET /api/v1/system/diagnostics` (administrators; no secrets or full paths). See [docs/API.md](docs/API.md).
