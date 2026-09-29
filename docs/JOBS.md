# Processing jobs

## States

A video job is a `sessions` row; its state is stored there, so it survives a restart even though the worker does not.

```
CREATED → QUEUED → DECODING → PROCESSING → AGGREGATING → (AUDIO_INTELLIGENCE stage) → GENERATING_REPORT → COMPLETED
                                   └──────────────────────────────── any error ─────────────────────────→ FAILED
LIVE sessions: INITIALIZING → PROCESSING → GENERATING_REPORT → COMPLETED   (STOPPED if the stream ends without STOP)
```

`failure_code` is a stable code (`VIDEO_DECODING_FAILED`, `MODEL_OR_PROCESSING_FAILED`, `JOB_INTERRUPTED`,
`LIVE_PROCESSING_FAILED`); `internal_error_reference` matches the server log so a user-visible message never exposes internals.

## Guarantees

- **Atomic claim.** A worker takes a job with one conditional `UPDATE … WHERE status NOT IN (claimed states)`. Two workers can never both run the same job.
- **Idempotent retry.** `POST /jobs/{job_id}/retry` atomically moves `FAILED → QUEUED` (`retry_count` +1). A second concurrent or repeated retry receives `409 JOB_NOT_RETRYABLE`; nothing is queued twice.
- **No duplicate reports.** `reports` has a unique `(session_id, format)`. Report writes are upserts; downloading the same report twice never creates a second row.
- **Safe failure.** Any exception ends in `FAILED` with a code and an internal reference; partial derived rows are replaced by the next attempt. Optional audio failure never invalidates completed visual evidence.
- **Explicit recovery.** Jobs run inside the API process, so work in progress when the server stops or restarts **cannot continue**; the row stays in a running state. Nothing rewrites it automatically. Such sessions show a **Stale** badge in Sessions and a banner in Session Details. An administrator opens *Settings → System → Sessions that look stuck*, reviews the preview (`GET /v1/system/jobs/stale`, which changes nothing), selects the video jobs to mark failed and confirms (`POST /v1/system/jobs/recover?confirm=true&session_ids=…`). Each change is audited with the acting user. The jobs can then be retried from Reports; retry is idempotent. A job that a worker in this process currently owns is never listed or changed, and interrupted **live-camera** sessions are reported for information only (a live capture cannot be resumed) and left unchanged. A second recovery call finds nothing to do.

## Runner modes (`JOB_RUNNER_MODE`)

| Mode | Behaviour |
|---|---|
| `IN_PROCESS` (default) | Runs after the response in the API process (FastAPI background task, or a daemon thread). **Appropriate for local and demo use. Not durable: jobs end when the process ends, and CPU-heavy work shares the API's resources.** |
| `QUEUE` | An interface (`QueueJobRunner`) for an external broker adapter. **No adapter is bundled; selecting it makes the API refuse to start.** |

Worker health is exposed in `/api/ready` (`job_runner`) and `/api/v1/system/diagnostics` (`mode`, `durable`, `queue_depth`, `stale_jobs`).
