# AmbiSense Architecture

The React/Vite client calls the FastAPI REST API and uses session WebSockets. Uploaded videos enter a persisted `QUEUED` session, then move through `INITIALIZING`, `PROCESSING`, `FINALIZING`, and `COMPLETED`. The processor samples frames, runs anonymous YOLO/ByteTrack detection plus optional MediaPipe face/pose landmarks, validates derived metrics, persists snapshots/tracks/quality, and creates an annotated output.

Live browser frames use `/ws/live/{session_id}`. Stored-session updates use `/ws/sessions/{session_id}` with sequence numbers; the client rejects duplicates and reconnects with bounded exponential backoff. SQLite is the local default and PostgreSQL is supported through `DATABASE_URL`. Alembic owns normalized schema migrations; the additive SQLite compatibility helper remains for existing local databases.

Privacy boundary: track UUIDs are session-local and anonymous. There is no face recognition, cross-session matching, or raw face-crop storage.

Classroom layouts are versioned and store normalized polygons. Sampled anonymous box centers are matched to the active layout and exposed only as session-scoped region aggregates. Activity segments modify metric relevance and limitations. Event review controls report inclusion without rewriting source evidence.

Reference images are validated and retained in the configured classroom-reference directory. Region preview reads only the latest stored anonymous observations and is clearly marked preview-only. Heat maps aggregate existing observations by region and requested time window; missing evidence remains unavailable. A lightweight development scheduler archives or deletes only explicit test/API sessions and writes an idempotent cleanup audit ledger.

When explicitly enabled, the Priority 3 path uses FFmpeg to extract mono PCM audio and stores quality/coverage metadata. A provider adapter may create anonymous timestamped transcript segments; unavailable providers create no text. Extractive discourse/content records retain transcript evidence IDs. Fusion persists methodology version, configured/effective weights, confidence, coverage, and limitations.

The shared cleanup scheduler also enforces raw audio/transcript retention and records actions in `cleanup_audits`; aggregate discourse/fusion remains available after raw evidence removal. Transcript exports reuse the report directory and are denied after retention deletion. Context rules and Priority 2 review states determine fusion inclusion, with exclusions retained in the Evidence Graph. The diarization protocol accepts session-local time spans only and deliberately discards provider identity/cluster labels.

Priority 4 introduces opt-in RBAC, signed expiring tokens with revocation, courses/memberships, classroom ownership, session-course links, deduplicated notifications, versioned notes, and audit entries. A centralized boundary authenticates every protected HTTP route and resolves session, classroom, course, transcript, event, content, report, layout and note parents before access. List/search/dashboard results are filtered to accessible sessions. WebSockets authenticate before acceptance. Authentication-disabled development resolves to an explicit local administrator; `AUTH_MODE=DEVELOPMENT` is the only mode that accepts `X-User-Id`, while `AUTH_MODE=TOKEN` never does.

The shared session-evidence envelope drives classroom/course dashboards, comparisons, UTC daily/weekly/monthly trends, rolling averages, alerts, and CSV/JSON/PDF aggregate exports. Missing evidence remains null, activity contexts and methodology versions are separated, and every aggregate identifies contributing sessions, coverage, confidence, exclusions and limitations.
