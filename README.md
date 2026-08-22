# AmbiSense

**Ambient Classroom Intelligence & Engagement Suite** is a privacy-conscious classroom video analytics research prototype. It combines anonymous person tracking, estimated engagement signals, occupancy, optional environment/safety models, persistent sessions, natural-language analytics filters, and a modern dashboard.

> AmbiSense does not make medical, psychological, or pedagogical diagnoses. Visual attention, engagement, emotion, and possible fatigue indicators are uncertain estimates and must not be used as the sole basis for decisions about students.

## Features

- MP4, AVI, MOV, and MKV upload with non-blocking background processing
- YOLO person detection and ByteTrack anonymous IDs in real mode
- Configurable frame skipping and CPU/CUDA selection
- Pure, tested EAR, MAR, head-direction, attention smoothing, engagement, fatigue, and seat-occupancy components
- FastAPI REST API, Swagger documentation, WebSocket session updates
- SQLite development persistence with PostgreSQL configuration support
- React 18, TypeScript, Tailwind, Recharts dashboard
- Persistent sessions, timeline, summaries, alerts, deterministic natural-language search
- CSV and PDF session reports
- Clearly labelled simulated data when `DEMO_MODE=true`
- Existing fire, projector, face, and noise processors preserved as optional legacy integrations

## Architecture

```text
Video / webcam / future RTSP
  -> sampled frames
  -> YOLO person detection
  -> ByteTrack anonymous tracking
  -> optional face landmarks and derived EAR/MAR/head pose
  -> estimated attention, engagement, fatigue, occupancy
  -> background processor
  -> SQLite/PostgreSQL
  -> FastAPI + WebSocket
  -> React dashboard and reports
```

The backend is under `backend/app`, reusable CV logic is under `backend/app/cv`, the React app is under `frontend`, and the original project files remain at the repository root.

## Windows setup

Requirements: Python 3.11+ and Node.js 20+.

```powershell
Copy-Item .env.example .env
python -m pip install -r backend\requirements.txt
Set-Location frontend
npm install
Set-Location ..
.\start_all.ps1
```

Open:

- Dashboard: http://localhost:5173
- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs

## Linux/macOS setup

```bash
cp .env.example .env
python -m pip install -r backend/requirements.txt
npm --prefix frontend install
uvicorn backend.app.main:app --reload --port 8000
npm --prefix frontend run dev
```

## Configuration

Copy `.env.example` to `.env`. Important variables include `DATABASE_URL`, `YOLO_MODEL`, `PROCESS_EVERY_N_FRAMES`, `EMA_ALPHA`, `EAR_THRESHOLD`, `YAWN_THRESHOLD`, `DROWSINESS_DURATION`, and `DEMO_MODE`.

Real analytics are the default. `DEMO_MODE=true` explicitly enables simulated analytics from a valid uploaded video's duration. Real mode uses YOLO/ByteTrack and the local MediaPipe Face Landmarker task. It may download `yolov8n.pt` on first use unless `YOLO_MODEL` points to a local compatible person-detection model.

## Upload and live analytics

Open `/upload`, select a supported classroom recording, and start analysis. The API creates a persistent session and processes it in a background task. `/ws/analytics/{session_id}` streams current progress and metrics once per second. Completed sessions contain summaries, timelines, search matches, and report downloads.

## API

The API implements upload, session start/stop/list/detail, analytics, anonymous students, timeline, report, dashboard summary/trends, occupancy, engagement, search, health, and WebSocket routes. Use the live OpenAPI page at `/docs` for request schemas.

## Tests

```powershell
python -m pytest -q
npm --prefix frontend run build
```

## Docker

```powershell
docker compose up --build
```

The Compose topology includes backend, frontend, PostgreSQL, and Redis. Local development uses SQLite and FastAPI background tasks. Redis is reserved for a future Celery deployment.

## Models

The supplied `fire.pt`, `projector_best.pt`, and `face_detection_model.pt` are preserved. Real anonymous student detection uses the configurable `YOLO_MODEL`. MediaPipe Tasks Face Landmarker is connected through `models/face_landmarker.task`; its landmarks drive PnP pose, EAR, MAR, attention, possible-drowsiness, and yawn estimates.

## Privacy and retention

- Tracking IDs are temporary and anonymous; identity recognition is not enabled by default.
- Raw face crops are not stored by the AmbiSense pipeline.
- Uploaded videos remain locally under `videos/` until an operator applies a retention policy.
- Institutions must obtain consent and define lawful retention/access policies before deployment.
- Automated attention and expression inference has demographic, camera-angle, occlusion, and context limitations.

## Performance and limitations

Frame skipping is configurable and CUDA is used when available. CPU inference speed depends on resolution and class size. The current background task runner is suitable for one-machine development; production should use Celery/Redis, authentication, object storage, database migrations, rate limiting, and HTTPS. RTSP/webcam capture, manual seat-region editing, replaceable emotion inference, and full landmark overlays are extension points rather than production-complete features.

## Screenshots

- `docs/screenshots/dashboard.png` — dashboard placeholder
- `docs/screenshots/session.png` — session detail placeholder

## Recommended next improvements

Add a tested MediaPipe Tasks adapter for the deployment Python version, live annotated frame transport, manual seat-region drawing, Alembic migrations, user authentication/RBAC, Celery workers, object-storage retention jobs, and calibrated validation using consented classroom datasets.
