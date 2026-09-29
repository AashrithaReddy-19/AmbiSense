# Troubleshooting

Every API error includes a `request_id`; search for it in `logs\ambisense.log` (and `logs\backend.err.log`).

| Symptom | Likely cause and fix |
|---|---|
| API exits at start with `Invalid AmbiSense configuration` | A setting failed validation. The message names it (`AUTH_SECRET_KEY`, `CORS_ORIGINS`, `UPLOAD_DIR`…). Fix `.env` and restart. |
| `GET /api/ready` returns 503 | Read the failing check: `database` (URL/permissions), `models` (`YOLO_MODEL` file or `ultralytics` missing), `storage` (directory not writable), `job_runner`. |
| Dashboard shows "Development mode: authentication is disabled" | Expected locally. Enable `AUTH_ENABLED=true` with a strong `AUTH_SECRET_KEY` before sharing. |
| Upload rejected | The message/`error.code` says why: unsupported format/MIME, empty file, too large (`MAX_UPLOAD_MB`), too long (`MAX_VIDEO_DURATION_MINUTES`), undecodable codec (`VIDEO_DECODING_FAILED`; re-encode to H.264 MP4). |
| Session stuck in PROCESSING after the server restarted | In-process jobs end with the process. *Settings → System → Mark interrupted jobs as failed*, then *Retry* in Reports. |
| Report/CSV download says "not available" | The session is not COMPLETED, that format was not generated, or the file was deleted. The Artifacts tab lists what exists. |
| `429 RATE_LIMITED` | Too many requests from one IP within a minute; wait `Retry-After` seconds or raise the `RATE_LIMIT_*` value. |
| Analytics chart is empty / has gaps | Gaps mean unavailable evidence, not zero. Read the *Reason* column in the table, or lower *Minimum coverage*. Check *Data source* (REAL is the default; demo/test data are separate). |
| Search returns nothing | Only sessions you may access, in the chosen data source, are searched. See "How your question was interpreted" for the filters that actually ran and the ones that did not. |
| Live page cannot use the camera | Browsers allow the camera only on `localhost` or HTTPS, and the user must grant permission. |
| Live page says models unavailable | Place `face_landmarker.task` and `pose_landmarker_lite.task` under `models\`; see Settings → Models. |
| `start_all.ps1` uses ports other than 8000/5173 | Those ports were busy; it picked the next free ones and printed them. |
| Vite build warns about chunk size | It should not: the build splits `charts` and `react` vendor chunks. If it returns, check `frontend/vite.config.ts` and that no page imports Recharts eagerly. |
| `alembic upgrade head` fails on a new database | Expected: the chain assumes an existing base schema. Use `python scripts\init_database.py`. |
| Tests leave files in `videos/` or `reports/` | They should not (see [TESTING.md](TESTING.md)). Check nothing overrides `UPLOAD_DIR`/`REPORT_DIR`. |
| Everything looks like the wrong theme | *Match system theme* follows the OS; use the sun/moon switch in the header for an explicit choice. |
