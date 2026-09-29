# AmbiSense architecture

```
Browser (React + TypeScript + Vite, Recharts, route-level code splitting)
   │  REST  /api/*      WebSocket  /ws/live/{id}, /ws/sessions/{id}
   ▼
Nginx (containers)  ──►  FastAPI  ──►  SQLAlchemy ──► SQLite (local) / PostgreSQL (containers)
                          │  │
                          │  └─ services: jobs, retention, layout_validation, rate_limit, startup_checks,
                          │     settings_catalog, audio_capabilities, semantic_search, report_generator, analytics
                          ▼
                    VideoProcessor (in-process job runner)
                          │ frames → YOLOv8 person detection → ByteTrack anonymous tracks
                          │        → MediaPipe face/pose landmarks (when models are present)
                          │        → per-interval snapshots with canonical metric availability
                          ▼
                    videos/ (uploads, annotated video)   reports/ (PDF, CSV, metrics CSV)
```

The legacy Flask/DeepFace prototype at the repository root is **not** part of this architecture (see README).

## Request path and cross-cutting behaviour

1. **Request-ID middleware** (outermost): accepts a well-formed `X-Request-ID` or generates one; logs method, path (never the query string), status and duration; adds the ID to every log record and error body.
2. **Trusted host / CORS** (explicit origins only).
3. **Authorization boundary**: when authentication is enabled, a middleware resolves the caller and enforces session/classroom/course access before the route runs; routes add permission dependencies (`require("…")`). Session lists use `bulk_accessible_sessions`, which evaluates access with a constant number of queries, and access is applied before pagination.
4. **Rate limiting** as route dependencies (login, upload, search, analytics, report): in-memory by default, Redis adapter optional.
5. **Error handlers** turn every failure into the canonical `{detail, error{code,message,details,request_id}}` shape; unexpected exceptions return only a reference.
6. **Start-up**: configuration is validated (invalid → refuse to start), tables are ensured, saved runtime settings are re-applied, and a cleanup scheduler archives or deletes test-flagged sessions and expired transcripts according to configuration.

## Data model highlights

`sessions` (state, source, activity context, classroom/course, data-source flags) → `analytics_snapshots` (per-interval metrics with canonical availability envelopes) · `quality_assessments` · `student_observations`/`anonymous_tracks` (session-local anonymous IDs) · `events` (with reviewer state) · `reports` (unique per session+format) · audio/transcript/discourse/fusion tables · `classroom_layouts` → `classroom_regions` (normalized polygons, versioned) · `users`, `courses`, `course_memberships` · `notifications` (per-user, de-duplicated) · `collaboration_notes` (versioned, author-attributed) · `audit_entries` and `cleanup_audits` (append-only).

There is no face image, embedding or identity column anywhere. Track IDs are meaningful only within one session.

## Evidence pipeline and availability

Each interval stores a `MetricAvailability` per metric (value, available, reason, coverage, confidence, valid/total observations). Session summaries, trends and comparisons aggregate **available** evidence only, weighted by coverage, grouped by activity context and methodology version. Unavailable is never averaged in as zero. See [docs/METRICS.md](docs/METRICS.md).

## Jobs, retention and deletion

Video jobs are rows in `sessions`, claimed atomically and retried idempotently ([docs/JOBS.md](docs/JOBS.md)). Deleting a session removes every dependent row (including notifications and session-scoped notes) in one transaction, then removes its files, **only when they resolve inside the configured upload/report directories**, and records the action in `audit_entries`. Artifact deletion keeps analytics evidence. Retention by age only *archives* (reversible).

## Performance decisions

- List endpoints avoid N+1: Reports use three grouped queries for any page size; trend, comparison, dashboard and filter endpoints load all per-session datasets in a fixed number of queries; access checks are batched. Query-count regression tests enforce this.
- Front end: Recharts (~400 KB) lives in a separate `charts` chunk loaded on demand; React and the router are a `react` chunk; heavier pages are route-level lazy chunks. The first load is the entry chunk plus `react`.
- Front-end polling (Reports) runs only while a job is active and is cleared on unmount; every request-driven view discards stale responses.

## Frontend structure

Pages under `frontend/src/pages`, shared UI under `components` (Tabs, Dialog/ConfirmDialog, States, StatusBadge, MetricValue, PrivacyNotice, Toast, Pagination…), state helpers under `hooks` (`useUrlFilters` keeps shareable filters in the URL with Apply/Reset; `useRemoteList`; `useUndoRedo`; `useUnsavedChangesGuard`), and the API client in `services`. Downloads go through the authenticated client so the bearer token is sent.
