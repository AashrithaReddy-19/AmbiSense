# AmbiSense

AmbiSense turns classroom video into **anonymous, aggregate, observable indicators**: an occupancy estimate, a
visual-orientation estimate, a possible-fatigue indicator, raised-hand observations and the quality of the evidence
behind each. It is a research prototype for supporting reflection, not for judging people.

> **What it does not do.** No facial recognition, no identity storage, no cross-session matching. Occupancy is an
> estimate and is **not verified attendance**. AmbiSense never says a student is attentive, disengaged, sleeping,
> cheating or performing well. These indicators must not be the sole basis for grading, discipline, attendance or
> other high-impact decisions.
>
> **Validation status: not validated on real classroom footage.** No verified accuracy or fairness result is
> currently available. See [docs/EVALUATION.md](docs/EVALUATION.md) for how a real evaluation would be run.

## Two systems live in this repository

| | Active: **AmbiSense** | Legacy: Flask/DeepFace prototype |
|---|---|---|
| Location | `backend/`, `frontend/`, `migrations/`, `scripts/` | `app.py`, `face_processing.py`, `fire.py`, `noice.py`, `projector.py`, `temp.py`, `templates/` |
| Stack | FastAPI, SQLAlchemy + Alembic, React + TypeScript + Vite, YOLOv8 + ByteTrack, MediaPipe | Flask, DeepFace |
| Status | Maintained | **Legacy / deprecated. Not integrated, and it performs facial recognition, which AmbiSense deliberately does not.** |

## Quick start (Windows)

Requirements: Python 3.11+ (3.13 is used in development), Node.js 20+.

```powershell
Copy-Item .env.example .env                      # optional: defaults work for local use
python -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend install
python scripts\init_database.py                  # only needed for a NEW database (the API also creates tables on start)
.\start_all.ps1                                  # API :8000 + dashboard :5173 (next free ports if taken)
```

Then open the dashboard at <http://127.0.0.1:5173>, the API docs at <http://127.0.0.1:8000/docs>, health at
`/api/health` and readiness at `/api/ready`. Stop with `.\stop_all.ps1`. Manual start:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Docker: `docker compose up --build` (see [DEPLOYMENT.md](DEPLOYMENT.md)). Redis is optional and off by default.

Starting the API never changes existing sessions: scheduled cleanup is opt-in (`SCHEDULED_CLEANUP_ENABLED`), and manual
cleanup, stale-job recovery, the orphan-notification repair and the artifact audit all preview first and change nothing
until you confirm (see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), [docs/JOBS.md](docs/JOBS.md) and [docs/TESTING.md](docs/TESTING.md)).

## What is in the application

Every capability is labelled honestly in [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md). In brief:

- **Overview, Live, Upload, Sessions, Session Details** (tabs: Overview, Timeline, Quality & Evidence, Regions, Artifacts, Notes)
- **Analytics** (trends with coverage/confidence filters and an accessible evidence table), **Compare** (2–5 sessions), **Reports** (filters, details drawer, safe downloads), **Search** (explicit, allowlisted filters with a truthful "how it was interpreted" panel), **Notifications**
- **Classroom Setup** (versioned polygon layouts with validation, undo/redo, zoom/pan, keyboard editing), **Management** (users, courses, classrooms, access), **Settings** (nine groups, validated, audited)
- **Privacy and retention** (archive, permanent session/artifact deletion with confirmation and audit trail)
- **Optional audio** (disabled by default, honest capability states) and an **evaluation framework** for future, consented validation

## Documentation

| Topic | File |
|---|---|
| Feature status (implemented / optional / partial / planned / legacy / not validated) | [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md) |
| Architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Development setup, environment variables | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), [.env.example](.env.example) |
| API overview, error contract, health/readiness | [docs/API.md](docs/API.md) |
| WebSocket contract | [docs/WEBSOCKET.md](docs/WEBSOCKET.md) |
| Job states, retries, runner modes | [docs/JOBS.md](docs/JOBS.md) |
| Metric definitions | [docs/METRICS.md](docs/METRICS.md), [METHODOLOGY.md](METHODOLOGY.md) |
| Privacy and ethics | [PRIVACY_AND_ETHICS.md](PRIVACY_AND_ETHICS.md) |
| Evaluation framework | [docs/EVALUATION.md](docs/EVALUATION.md), [MODEL_EVALUATION.md](MODEL_EVALUATION.md) |
| Deployment, Docker, Nginx, Alembic stamping | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Backup and restore | [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md) |
| Testing | [docs/TESTING.md](docs/TESTING.md) |
| Troubleshooting | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Demo guide | [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) |

`CURRENT_IMPLEMENTATION_AUDIT.md`, `IMPLEMENTATION_SUMMARY.md` and `PRIORITY4_ACCEPTANCE_AUDIT.md` are historical
snapshots and are not kept current.

## Tests and checks

```powershell
python -m pytest tests/ -q                       # backend (uses an isolated temporary database and artifact folders)
npm.cmd --prefix frontend test -- --run          # frontend unit/integration tests
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run build
```

The automated tests never touch `ambisense.db`, `videos/` or `reports/`.

## Known limitations

- Not validated on real classroom footage; no accuracy or fairness result exists yet.
- In-process job runner: right for local/demo use, not a durable production queue (see [docs/JOBS.md](docs/JOBS.md)).
- SQLite is the local default; the PostgreSQL path is supported but has had less use.
- Physical-webcam capture depends on a browser and camera; automated tests use mocked frames and small synthetic videos.
- Container images were not built in the environment used for the latest verification (no running Docker daemon); `docker compose config` validates.
