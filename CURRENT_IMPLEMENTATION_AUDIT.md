# AmbiSense Current Implementation Audit

Audit refreshed: 2026-08-22

## Priority 1 audit resolution

- The 395% display came from accumulating ByteTrack-local IDs and dividing by expected students without expiry or deduplication. Current occupancy now uses room capacity; valid unique tracks use duration, observation, confidence, timeout and re-entry gates; verified attendance remains unavailable.
- Blank live values came from treating missing landmark evidence as zero and from a client without reconnect/status handling. Metric envelopes now distinguish unavailable, insufficient, disabled, processing, failed, and measured-zero states.
- Stale `UPLOADING` status came from an unvalidated lifecycle. Jobs now progress through queued, initializing, processing, finalizing and completed states, with failure/stop paths and duplicate-job protection.
- `100000ms` was an FPS-derived frame interval, not measured latency. Unknown latency is now `null` and displayed as unavailable.
- Stored-session WebSockets now carry sequence numbers; the client rejects duplicates, reconnects with capped exponential backoff, and cleans up on unmount.
- Central validation, quality assessment, confidence/coverage envelopes, Alembic migration, and focused tests are implemented. Later work is accurately listed in `IMPLEMENTATION_STATUS.md`.

## Working end-to-end

- React 18/Vite/TypeScript SaaS dashboard with Dashboard, Live Classroom, Sessions, Upload, Search, Reports and Settings routes.
- FastAPI, SQLAlchemy and additive SQLite migrations; PostgreSQL-compatible configuration remains available.
- Safe MP4/AVI/MOV/MKV streaming uploads, configurable 500 MB limit, background processing, real progress/stage/FPS/ETA and persistent sessions.
- Real mode by default; demo rows are explicitly tagged `DEMO` and never presented as real analytics.
- YOLOv8 person detection with ByteTrack anonymous `Student_XX` IDs.
- MediaPipe Tasks Face Landmarker driving PnP head pose, EAR, MAR, temporal possible-drowsiness/yawn estimates and EMA visual-attention estimates.
- MediaPipe Pose Landmarker driving wrist-above-shoulder raised-hand participation estimates and hand transition events.
- Temporal distraction logic, Estimated Engagement Index, fatigue indicators, anonymous attendance/occupancy and event thresholds.
- Per-student observations, metrics, events, settings, seat configurations and reports persist without face crops or identity recognition.
- Annotated MP4 output contains anonymous boxes, states, head direction, raised-hand/drowsiness/yawn labels and aggregate overlay.
- Browser webcam frames can be sent to `/ws/live/{session_id}` for real backend inference; `/ws/sessions/{session_id}` streams stored processing analytics.
- Search combines deterministic numerical parsing with cached Sentence-BERT semantic intent fallback and database querying.
- CSV and PDF reports use stored metrics; PDFs include summary, insights, timeline chart, events, methodology and privacy notice.
- Settings persist thresholds, frame skip, aggregation, privacy, overlays, retention and demo mode.
- Ten automated tests pass; the React production build and real mechanical pipeline validation pass.

## API surface

- Health/model health: `GET /api/health`, `GET /api/models/health`
- Sessions: `POST/GET /api/sessions`, `GET/DELETE /api/sessions/{id}`, `POST /api/sessions/{id}/stop`
- Uploads: `POST /api/uploads` and compatibility route `/api/videos/upload`
- Analytics: `/api/sessions/{id}/metrics`, `/summary`, `/events`, `/students`, `/video`
- Dashboard: `GET /api/dashboard`, `/api/dashboard/trends`
- Search/reports/settings: `POST /api/search`, `GET /api/reports`, `GET /api/reports/{id}`, `GET/PUT /api/settings`
- Seat layouts/comparison: `GET/POST /api/seat-configurations`, `GET /api/session-comparison`
- WebSockets: `/ws/sessions/{id}`, `/ws/analytics/{id}`, `/ws/live/{id}`

## Models

- `yolov8n.pt`: person detection/tracking
- `models/face_landmarker.task`: official MediaPipe face landmarks
- `models/pose_landmarker_lite.task`: official MediaPipe pose landmarks/raised hands
- Existing `face_detection_model.pt`, `projector_best.pt` and `fire.pt` remain optional legacy integrations.
- `sentence-transformers/all-MiniLM-L6-v2` is cached locally for semantic intent matching.

## Honest remaining limitations

- The supplied repository still contains no real consented classroom recording. The real pipeline, persistence and annotation mechanics are validated with a synthetic video, but classroom accuracy is not empirically validated here.
- Automatic occupancy currently uses visible person boxes; manual seat regions can be saved through the API but the visual drawing editor and region-aware pipeline association remain incomplete.
- Session comparison is exposed by API but lacks a dedicated multi-select comparison chart in React.
- Browser live inference is functional for a single local development client; production requires a worker/queue and backpressure controls.
- Research heatmaps, raw per-frame inspection UI and a pose-specific calibrated classroom validation suite remain future work.
- MP4 browser compatibility depends on the OpenCV codec; production should transcode outputs to H.264 using FFmpeg.

## Privacy boundary

AmbiSense uses anonymous temporary tracking IDs, stores no face crops, and does not enable identity recognition. Attention, engagement and fatigue indicators are uncertain research estimates—not psychological, medical or pedagogical diagnoses.
