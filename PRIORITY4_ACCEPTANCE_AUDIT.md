# Priority 4 Final Acceptance Audit

> **Historical snapshot.** Written on an earlier date and **not kept current**. For the present state see [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md) and [README.md](README.md).

Audit date: 2026-08-24

## Result

Priority 4 is complete. Priority 5 was not started. Existing uncommitted Priority 1–4 work was preserved.

## Authentication gate

- Production `TOKEN` mode uses a deployment-provided secret of at least 32 characters, PBKDF2-SHA256 passwords with random salts and 310,000 rounds, signed tokens with issuer/audience/expiration, and database token-version revocation.
- Login, logout, invalid/expired tokens, disabled accounts, role-change revocation and final-administrator protection are tested.
- Plaintext passwords are neither modeled nor persisted. Authentication errors are generic.
- `X-User-Id` is accepted only in explicitly configured `DEVELOPMENT` mode. Authentication-disabled local mode resolves to a documented local administrator.
- Analytics and live WebSockets authenticate and authorize their session before accepting the connection.

## Authorization gate

All HTTP routes pass through the authentication boundary when authentication is enabled. The boundary resolves direct and nested session, classroom, course, report, transcript segment, event, generated-content and collaboration-note resources. Query parents used by capture, comparison, dashboards, trends and exports are also checked.

- Administrator-only: settings, cleanup/retention operations and user lifecycle management.
- Administrator/Instructor: uploads, session creation/lifecycle/archive/delete, classroom/course/layout/seat management and memberships.
- Administrator/Instructor/Reviewer: evidence review, transcript corrections, speaker roles, generated-content corrections and notes.
- Viewer: accessible aggregate/session/report reads only.
- Session lists, legacy dashboard summaries/trends, reports, natural-language search, occupancy and engagement responses are filtered to accessible sessions.
- Bulk archive validates every requested session before mutation.
- Course membership grants scoped course/session/classroom read access and is auditable; removal takes effect immediately.
- Notification ownership is enforced and alert generation considers accessible sessions only.

High-risk isolation tests cover list, search, report, note, content, aggregate export, archive, course membership, HTTP session access and WebSocket access.

## Analytics gate

- Trends implement UTC daily, ISO-weekly, monthly and session buckets.
- Rolling values use only compatible activity-context/methodology histories, require two available buckets, and return contributing counts.
- Missing evidence remains null. Buckets report contributing/total sessions, coverage, confidence and status.
- Invalid date ranges are rejected. Context and methodology versions are never silently mixed.
- Comparisons warn for context, coverage, methodology and insufficient-evidence differences. Unavailable metrics remain unavailable.
- Reviewer exclusions are counted for traceability and excluded from the context-aware fused evidence upstream.

## Dashboard and notification gate

The permission-aware React application includes selectable classroom/course dashboards with session timelines and participation, camera, audio and coverage charts. It exposes question/discourse values, calibrated region summaries, retained topic recurrence, limitations and explicit loading, empty, error, unavailable, insufficient and partial-evidence states. Trend date/period filters change API parameters.

Notifications are advisory aggregate evidence only. Categories cover camera, audio, provider/model availability, processing failure, insufficient evidence and participation change. Dedupe keys prevent repeated generation for the same evidence transition. Read, dismiss, category filtering and supporting evidence are displayed. No grading, discipline, emotion, intelligence, motivation or learning-ability decisions are generated.

## Export gate

Classroom, course and all-accessible aggregate exports support CSV, JSON and PDF. They include scope, UTC date range, included/excluded sessions and reasons, coverage, confidence, contexts, methodology versions, reviewer-exclusion counts, missing evidence and limitations. Archived sessions are excluded. Transcript-retention unavailability is explicit. Export scope and every included session are authorized.

## Migration gate

- Single head: `20260823_priority4_auth`.
- Offline `python -m alembic upgrade head --sql`: passed.
- Upgrade from a representative `20260823_priority4` users schema to head: passed and tested.
- The repository's original `ambisense.db` predates Alembic and has no version row. It must be backed up and stamped to its inspected matching revision before upgrades; this deployment fact is documented and the live database was not mutated during this audit.

## Verification

- Backend/API/CV/security/migration: 46 passed.
- Frontend Vitest: 13 passed.
- Frontend ESLint: zero warnings.
- Frontend production build: passed.
- Alembic head/offline SQL/representative upgrade: passed.
