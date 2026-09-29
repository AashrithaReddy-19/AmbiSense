# API overview

Interactive reference: `http://127.0.0.1:8000/docs` (OpenAPI). All paths below are under `/api` unless they start with `/ws`.

## Conventions

**Authentication.** With `AUTH_ENABLED=false` (default, development only) every caller acts as a local administrator.
With `AUTH_ENABLED=true`, send `Authorization: Bearer <token>` (obtained from `POST /v1/auth/login`). Roles:
`ADMINISTRATOR`, `INSTRUCTOR`, `REVIEWER`, `VIEWER`. Session access also depends on classroom ownership and course
membership. Authorization is enforced on the server for every request; hiding a control in the UI is only a convenience.

**Error contract.** Every error carries a canonical `error` object and, for backward compatibility, the legacy `detail`:

```json
{
  "detail": "…legacy string or structure…",
  "error": { "code": "VIDEO_DECODING_FAILED", "message": "The video could not be decoded.", "details": null, "request_id": "9f2c…" }
}
```

`request_id` matches the `X-Request-ID` response header (a well-formed `X-Request-ID` you send is echoed) and the
server log line. Validation errors (`422`, code `VALIDATION_FAILED`) list field locations and messages but never echo
submitted values. Unexpected failures return a generic `500 INTERNAL_ERROR` with only the reference.

Common codes: `INVALID_DATE_RANGE`, `INVALID_COVERAGE`, `INVALID_CONFIDENCE`, `INVALID_DATA_SOURCE`, `INVALID_FORMAT`,
`INVALID_METRIC`, `INVALID_PERIOD`, `SESSION_NOT_FOUND`, `SESSION_ACCESS_DENIED`, `DUPLICATE_SESSION_IDS`,
`TOO_FEW_SESSIONS`, `TOO_MANY_SESSIONS`, `UNSUPPORTED_VIDEO_FORMAT`, `UNSUPPORTED_MIME_TYPE`, `EMPTY_FILE`,
`FILE_TOO_LARGE`, `VIDEO_DECODING_FAILED`, `VIDEO_TOO_LONG`, `INVALID_ACTIVITY_CONTEXT`, `INVALID_SESSION_NAME`,
`JOB_NOT_FOUND`, `JOB_NOT_RETRYABLE`, `SOURCE_VIDEO_UNAVAILABLE`, `SESSION_ACTIVE`, `CONFIRMATION_REQUIRED`,
`INVALID_ARTIFACT_KIND`, `INVALID_LAYOUT`, `RISKY_CHANGE_REQUIRES_CONFIRMATION`, `NOTE_EDIT_FORBIDDEN`, `RATE_LIMITED`.

**Data source.** `data_source` is `REAL` (default), `DEMO`, `TEST` or `ALL`. REAL and DEMO exclude test-flagged sessions;
TEST is exactly the test-flagged sessions.

**Rate limiting.** Per client IP, per minute (`RATE_LIMIT_*_PER_MINUTE`). Over the limit: `429 RATE_LIMITED` with `Retry-After`.
Buckets: login, upload, search, analytics (trends/compare/filter), report (report generation, report list, aggregate report).

**Pagination.** List endpoints that return objects use `page`, `page_size`, `total`, `pages`. Endpoints that return arrays
(users, notifications) report totals in `X-Total-Count` (and `X-Unread-Count` for notifications).

## Health, readiness, diagnostics

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness. Lightweight; no database or model access. Includes upload limits and device. |
| `GET /ready` | Readiness: `database`, `models`, `storage`, `job_runner`. `200 {"status":"ready"}` or `503 {"status":"not_ready"}` with per-check detail (no paths or secrets). |
| `GET /v1/system/diagnostics` | Administrators. Database dialect and migration revision, job-runner health, readiness, configuration warnings (setting names only), model file names. Never returns secrets, tokens, SQL, private data or full paths. |
| `GET /v1/system/jobs/stale` | Administrators. **Read-only preview** of sessions that claim to be running although no worker or camera connection in this API process owns them: `items` (id, name, status, `age_minutes`, `kind`, `recoverable`, `reason`), `explanation`, `not_running` counts. Changes nothing. |
| `POST /v1/system/jobs/recover?confirm=true[&session_ids=1&session_ids=2]` | Administrators. Marks the **stale video jobs** FAILED (retryable), optionally only the listed ids. Needs `confirm=true`; writes one `JOB_RECOVERED` audit entry per session with the acting user. Never runs automatically, never touches a job a live worker owns, never changes live-capture sessions. Idempotent: a second call recovers nothing. |
| `GET /v1/system/cleanup-test-sessions/preview` | Administrators. Read-only: the test-flagged sessions a cleanup would archive/delete now. |
| `POST /v1/system/cleanup-test-sessions?confirm=true` | Administrators. Explicit, audited test-session cleanup (works even when scheduled cleanup is off). Without `confirm=true`: `400 CONFIRMATION_REQUIRED`. |

Session payloads carry three additive, computed fields: `stale` (bool), `stale_kind` (`STALE_VIDEO_JOB`, `LIVE_CAPTURE_INTERRUPTED` or null) and `stale_reason`.

## Sessions and processing

`POST /uploads` (multipart: `file`, `name`, `classroom_id`, `course_id`, `activity_context`), `POST /sessions`,
`POST /sessions/{id}/stop`, `GET /v1/sessions` (filters: `q`, `status`, `mode`, `classroom_id`, `course_id`,
`activity_context`, `start_date`, `end_date`, `minimum_coverage`, `archived`, `include_tests`, `sort`, `page`, `page_size`),
`GET /sessions/{id}`, `DELETE /sessions/{id}?confirm=true`, `GET /jobs/{job_id}`, `POST /jobs/{job_id}/retry`,
`GET /sessions/{id}/analytics|timeline|events|students`, `GET /v1/sessions/{id}/quality|regions|artifacts`,
`GET /sessions/{id}/video?annotated=`, `GET /sessions/{id}/report?format=csv|pdf|metrics`,
`DELETE /v1/sessions/{id}/artifacts?kinds=…&confirm=true`, `PUT /v1/events/{id}/review`.

`minimum_coverage` is the fraction (0.0–1.0) of a session's processed samples with at least one detected person.
`start_date` > `end_date` returns `400 INVALID_DATE_RANGE`; a coverage outside 0–1 returns `400 INVALID_COVERAGE`.
Access control is applied before pagination.

## Analytics

| Endpoint | Notes |
|---|---|
| `GET /v1/analytics/trends` | `period` (session/daily/weekly/monthly), `metric`, `data_source`, `classroom_id`, `course_id`, `activity_context`, `start_date`, `end_date`, `minimum_coverage`, `confidence_min`, `include_archived`. Returns `points` (each with a canonical `result`), `filters_applied`, `excluded_by_filters`. Unavailable evidence is never converted to zero. |
| `POST /v1/analytics/compare` | 2–5 unique `session_ids`, `metrics`. Returns per-session `metric_results`, `event_counts`, compatibility notices. |
| `GET /v1/analytics/compare/export` | CSV; user-controlled text is protected against spreadsheet formula injection. |
| `GET /v1/dashboard/overview` | Bounded summary (constant number of queries). |
| `GET /v1/reports` | Filters: `q`, `source_type`, `status`, `activity_context`, `format`, `start_date`, `end_date`, `classroom_id`, `course_id`, `data_source`, `page`, `page_size`. Items include `available_formats` and `report_ready`. Newest first. Constant query count regardless of page size. |
| `POST /search` (`/v1/search`) | `{query, data_source}`. Returns `interpreted_filter`, **`applied_filters`** and **`not_applied`** (the only filters that ran), `match_kind`, bounded `matches` (max 100) and `bounded`. Authorization and data-source separation are applied to every match after matching. |

## Management, settings, privacy

`GET/POST/PUT /v1/users` (administrators; `GET` supports `q`, `role`, `active`, `page`, `page_size`), `GET /v1/auth/permissions`,
`GET/POST/PUT /v1/classrooms`, `POST /v1/classrooms/{id}/archive`, `GET/POST /v1/classrooms/{id}/layouts`,
`POST /v1/layouts/validate` (dry run), `GET/POST/PUT /v1/courses`, `…/courses/{id}/members`, `…/courses/{id}/sessions`,
`GET/POST /v1/notes`, `PUT /v1/notes/{id}` (author or administrator; optimistic `version`),
`GET /v1/notifications`, `POST /v1/notifications/{id}/read|dismiss`, `POST /v1/notifications/read-all`,
`GET /v1/settings/catalog`, `GET/PUT /settings` (`?confirm_risky=true` for risky changes), `GET /v1/audio/capabilities`,
`GET /v1/evaluation/status`, `GET /v1/retention/policy`, `POST /v1/retention/sessions/run?confirm=true`.

### Capability contract: `GET /v1/audio/capabilities`

```json
{ "status": "DISABLED | NOT_CONFIGURED | MODEL_UNAVAILABLE | READY", "reason": "…",
  "audio_processing_enabled": false, "ffmpeg_available": false,
  "transcription": { "configured": false, "provider": "NONE", "model_available": false, "model": null },
  "diarization": { "configured": false, "provider": "NONE", "model_available": false, "note": "…" },
  "identity": "anonymous" }
```

A capability is never reported operational unless it is configured and its model/library/binary is present.

## Settings catalogue

`GET /v1/settings/catalog` lists only real, supported settings with `group`, `unit`, `min`/`max`, `choices`, `editable`,
`restart_required` and `risky`. Environment-controlled values are `editable: false`. Secrets (`AUTH_SECRET_KEY`,
`REDIS_URL`, `DATABASE_URL`) are never included. A risky change without `confirm_risky=true` returns
`409 RISKY_CHANGE_REQUIRES_CONFIRMATION`; every applied change is written to the audit trail.
