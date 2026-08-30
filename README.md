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
alembic upgrade head
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

## Classroom calibration and activity context

Open `/classroom-setup` to draw normalized seat, zone, instructor, projector, entrance, exit, or excluded-area polygons and save a new layout version. Assign that classroom to a session to enable calibrated aggregate region summaries. Without a calibrated layout, AmbiSense reports estimated unoccupied capacity rather than exact empty seats. Session Detail supports activity-context changes and event confirmation, uncertainty, or report exclusion.

Reference JPG, PNG, or WEBP images can be uploaded in Classroom Setup, or captured from a locally retained session video. The editor supports bounded region movement and vertex editing. Its preview uses temporary anonymous track labels only. Heat maps expose explicit availability, confidence, and coverage rather than converting missing evidence to zero.

Development cleanup runs at startup and then at `TEST_SESSION_CLEANUP_INTERVAL_MINUTES`. It targets only sessions explicitly marked `is_test`, older than `TEST_SESSION_CLEANUP_AGE_HOURS`, and performs `TEST_SESSION_CLEANUP_ACTION=ARCHIVE|DELETE`. Disable it with `TEST_SESSION_CLEANUP_ENABLED=false`. Every change is recorded in `cleanup_audits`; real sessions are never eligible.

## Optional audio and lecture intelligence

Audio is disabled by default. `AUDIO_ANALYTICS_ENABLED=true` enables FFmpeg extraction and anonymous quality/voice-activity evidence. `TRANSCRIPTION_PROVIDER=FASTER_WHISPER` uses an installed local Faster Whisper model; disabled or missing dependencies produce explicit states and never fabricate text or fail visual analytics. Transcript-derived content is extractive and keeps evidence segment IDs/timestamps. Speaker roles default to `UNKNOWN`. Fusion excludes missing evidence and reports effective weights, confidence, coverage, limitations, and methodology version.

`TRANSCRIPT_RETENTION_ENABLED=true` runs idempotent cleanup through the existing scheduler. After `TRANSCRIPT_RETENTION_DAYS`, it removes the extracted WAV, transcript segments/corrections, anonymous speaker segments, chapters, and generated transcript content. It preserves permitted aggregate discourse/fusion records and writes `TRANSCRIPT_RETENTION` cleanup-audit entries. Transcript JSON, CSV, and text exports are available from Session Detail only while transcript evidence exists. Session PDF/CSV reports include available Priority 3 status, confidence, coverage, context, exclusions, and limitations without converting missing values to zero.

Fusion uses the confirmed activity context to include or exclude visual/audio/discourse components and renormalizes included weights. Reviewer-excluded or incorrect evidence is shown with its exclusion reason in the Evidence Graph and omitted from report events/fusion where applicable. Diarization is optional: `DIARIZATION_PROVIDER=NONE` is the default; `LOCAL_ADAPTER` exposes the adapter boundary but reports unavailable unless an operator supplies a compatible local adapter. Provider speaker labels are discarded, roles remain anonymous, and permitted roles can be assigned manually per segment.

## Multi-classroom and course management

Priority 4 adds normalized users, roles, course memberships, classroom ownership, session-course assignment, aggregate dashboards, comparisons, UTC daily/weekly/monthly trends, advisory notifications, optimistic-lock notes, audit entries, advanced evidence filtering, and aggregate CSV/JSON/PDF exports. `AUTH_ENABLED=false` preserves the local administrator workflow. For signed production-style sessions set `AUTH_ENABLED=true`, `AUTH_MODE=TOKEN`, and a random `AUTH_SECRET_KEY` of at least 32 characters. `AUTH_MODE=DEVELOPMENT` explicitly enables the local `X-User-Id` adapter; never use that mode in production. HTTP and WebSocket resources enforce Administrator, Instructor, Reviewer, or Viewer permissions.

Aggregates average only available evidence and report contributing-session counts, coverage, confidence, contexts, methodology versions, and limitations. Comparisons warn about incompatible contexts, large coverage differences, or methodology changes. Notifications are deduplicated and advisory; notes use version checks to prevent silent overwrite.

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
