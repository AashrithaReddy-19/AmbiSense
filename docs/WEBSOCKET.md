# WebSocket contract

Two WebSocket families exist. Both authenticate before the connection is accepted: pass `?access_token=<jwt>` (token
mode) or `?user_id=<id>` (development auth mode). When authentication is disabled no parameter is needed. A caller
without access to the session is closed with **code 1008** (policy violation). Query strings are never logged.

## `/ws/live/{session_id}` - browser camera analysis

For a `LIVE` session only; requires the `ADMINISTRATOR` or `INSTRUCTOR` role. If the session is missing or is not a live session the server sends `{"error": …}` and closes with 1008.

**Client → server**

| Message | Meaning |
|---|---|
| binary | One JPEG camera frame. Undecodable frames get `{"error": "Invalid camera frame"}` and are skipped. |
| text `PING` | Keep-alive; answered with `pong`. |
| text `STOP` | Explicit stop: the server finalises the session and generates reports. Closing the socket without `STOP` marks the session `STOPPED` (no report). |

**Server → client**

```json
{ "type": "status", "stage": "CAPTURING_LIVE_CAMERA", "message": "Models loaded; waiting for camera frames" }
{ "type": "pong", "session_id": 5, "timestamp": "2026-09-28T09:00:00Z" }
{ "type": "live_metrics", "session_id": 5, "sequence": 12, "timestamp": "…Z",
  "pipeline": { "camera_connected": true, "frames_transmitting": true, "backend_receiving": true, "models_loaded": true, "inference_running": true, "metrics_aggregating": true, "live_updates_connected": true },
  "transport": { "fps": 2.4, "latency_ms": 180.2, "frames_received": 12, "frames_processed": 12 },
  "metrics": { "<metric name>": { "value": 3, "available": true, "reason": null, "coverage": 1, "confidence": 0.9, "valid_observations": 1, "total_observations": 1 } },
  "student_count": 3, "occupancy_rate": 7.5, "annotated_image": "<base64 JPEG>", "privacy_mode": true }
{ "error": "Live processing failed", "reference": "ab12cd34ef56" }
```

`metrics` uses the **canonical metric-availability contract** only (`value, available, reason, coverage, confidence,
valid_observations, total_observations`). It includes `occupancy`, `unoccupied_capacity`, `prolonged_eye_closure`,
`yawning`, `raised_hands`, `frame_quality` and, when evidence exists, `visual_orientation`,
`observable_participation`, `possible_fatigue`. A missing value is `available: false` with a `reason`, never `0`.
Legacy convenience fields (`student_count`, `attention`, `drowsiness`, …) are kept for older clients. `latency_ms` is
measured inference time; unknown values are `null`. `reference` in an error is a support reference matching the server log.

## `/ws/sessions/{session_id}` and `/ws/analytics/{session_id}` - stored-session progress

Read-only. The server sends a `snapshot` about once per second:

```json
{ "type": "snapshot", "sequence": 41, "server_time": "…Z", "session_id": 5, "status": "PROCESSING", "stage": "PROCESSING",
  "progress": 63.5, "processed_frames": 190, "total_frames": 300, "processing_speed": 11.2, "eta_seconds": 10, "analytics": { … } }
```

`sequence` increases monotonically; clients ignore duplicates or out-of-order messages and reconnect with capped
exponential backoff (the dashboard does both). `status` is `NOT_FOUND` if the session does not exist.

## Behind Nginx

`/ws/` is proxied with `Upgrade`/`Connection` headers and a one-hour read timeout (see `frontend/nginx.conf`). Browser
camera access requires HTTPS or `localhost`.
