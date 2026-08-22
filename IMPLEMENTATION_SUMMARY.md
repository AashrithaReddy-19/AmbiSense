# AmbiSense Phase 2 Implementation Summary

## Files created

- `CURRENT_IMPLEMENTATION_AUDIT.md`
- `backend/app/cv/face_landmarks.py`
- `models/face_landmarker.task` (official MediaPipe task bundle)
- `scripts/validate_real_pipeline.py`
- `frontend/src/pages/LivePage.tsx`
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- This implementation summary

## Files modified

- Backend configuration, database, models, schemas, main API, video processor, semantic search, requirements, and Docker configuration
- Existing React app routing, dashboard, sessions, session details, search, shared types, and styles
- `.env.example`, README, workflow test, and Docker Compose defaults

## APIs added

- `GET /api/models/health`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/sessions/{id}/events`
- `GET /api/sessions/{id}/video?annotated=true|false`
- `GET /api/reports`
- `GET /api/session-comparison?ids=1,2`

Existing session, upload, analytics, dashboard, search, report, health, and WebSocket APIs were retained and expanded.

## CV modules and real pipeline

- Real mode is now the default; demo mode remains an explicit saved setting.
- YOLOv8 person detection and ByteTrack generate anonymous `Student_XX` IDs.
- MediaPipe Tasks Face Landmarker runs in video mode.
- MediaPipe Tasks Pose Landmarker detects raised-hand participation from wrist/shoulder geometry.
- Detected face centers are associated with tracked person boxes.
- PnP derives yaw, pitch, roll, and head direction.
- Landmark geometry derives EAR and MAR.
- Temporal engines derive eye state, possible prolonged closure, and sustained-mouth-opening yawn events.
- EMA produces an Estimated Visual Attention score.
- Measured signals feed Estimated Engagement and Fatigue indices.
- The pipeline saves snapshots, anonymous student observations, and events without face crops.
- Temporal distraction and event rules generate high-distraction, attendance, fatigue, engagement, hand, yawn and drowsiness events.
- Processing writes `reports/annotated_<session_id>.mp4` with boxes, IDs, states, head direction, and aggregate overlays.

## Database changes

The additive migration preserves existing sessions and adds processing stage, duration, FPS, total/processed frames, speed, ETA, analytics mode, and annotated-video path. New tables include `student_observations`, `events`, and persistent `settings`. Existing analytics, seat configurations, alerts, and reports remain intact.

## Frontend changes

- Dashboard distinguishes REAL ANALYTICS and DEMO MODE and shows current processing context.
- Sessions auto-refresh and show stage, real progress, frames, speed, and ETA.
- Session details include metadata, annotated video, metrics, charts, events, summary, CSV, and PDF controls.
- Live Classroom consumes the real analytics WebSocket, displays metrics/timeline, and supports local browser-camera preview.
- Live Classroom also sends browser-camera frames to backend YOLO/MediaPipe inference and displays returned overlays.
- Reports lists completed sessions with real export controls.
- Settings exposes classroom, vision, attention, drowsiness, yawning, data, demo-mode, and model-health controls.
- Search displays database-backed, clickable results with metric, time, value, and reason.

## Run

```powershell
.\start_all.ps1
```

- Dashboard: http://localhost:5173
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Test

```powershell
python -m pytest -q
npm --prefix frontend run build
python scripts\validate_real_pipeline.py path\to\classroom-video.mp4
```

The automated suite has 10 passing tests. A real-mode mechanical run completed on CPU with Face and Pose Landmarker, generated five persisted REAL snapshots, and produced an annotated MP4. Sentence-BERT fallback was downloaded, cached and validated. The bundled validation input is synthetic and therefore cannot validate classroom behavioral accuracy.

## Known limitations

- A real, consented classroom recording was not supplied, so real person, head-pose, EAR, MAR, attention, and yawn accuracy has not been empirically validated in this workspace.
- Browser webcam preview is implemented, but browser frames are not yet uploaded to a backend inference WebSocket; the analytics WebSocket streams server-side session results.
- Seat totals are configurable and occupancy is derived from visible people. Interactive drawing and persistence of a visual seat-region map remains future work.
- Session comparison is available by API but does not yet have a dedicated comparison page.
- Sentence-Transformers is health-checked, while search currently uses deterministic parsing and ranking rather than loading a large embedding model.
- PDF reports export real session summaries but still need embedded chart graphics and a detailed timeline appendix.
- BackgroundTasks is suitable for local development; production deployments should move inference to Celery/Redis.
- MP4 browser playback depends on the system OpenCV codec. Production should transcode to H.264 with FFmpeg.
