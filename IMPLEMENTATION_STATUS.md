# Implementation Status

## Priority 1

- Audit, validation, occupancy correction, anonymous track lifecycle, local session state machine, pipeline health, WebSocket reconnection, camera quality, and metric confidence/coverage: **Complete**.
- Durable live-camera resume across backend restarts: **Partial** — this requires the Priority 5 worker architecture.
- Advanced multi-frame obstruction/motion/camera-angle quality calibration: **Partial** — basic brightness, contrast, blur, landmark coverage and warnings are complete.

## Priority 2

- Reference-frame JPG/PNG/WEBP upload with decoding/size validation, classroom/layout association and UI states: **Complete**.
- Reference-frame capture from a retained session video at a selected timestamp: **Complete**.
- Interactive normalized polygon drawing, selection, vertex dragging/removal, region movement, validity protection and versioned save: **Complete**.
- Privacy-safe latest-track matching preview with two-second refresh, matched/unmatched/excluded states and unavailable evidence handling: **Complete**.
- Occupancy, raised-hand, participation-signal, camera-visibility and model-confidence heat maps with time, interval, region and session-comparison controls: **Complete**.
- Reviewer-note create/edit/save UI with review and report-inclusion preservation: **Complete**.
- Safe multi-select and filtered-page bulk archive with confirmation and result feedback: **Complete**.
- Configurable scheduled test/API cleanup with ARCHIVE/DELETE actions, explicit `is_test` targeting, idempotency, real-session protection and audit ledger: **Complete**.
- Session search/filter/pagination, activity context, event debounce/review, region summaries and report exclusion: **Complete**.

## Verification

- Backend/API/CV suite: **46 passed**, including Priority 4 security isolation and migration tests.
- Frontend Vitest suite: **13 passed**, including aggregate dashboard states.
- Frontend ESLint: **Passed with zero warnings**.
- Frontend production build: **Passed**.
- Alembic upgrade from a representative legacy schema: **Passed to `20260823_priority2_complete`**.
- Alembic offline SQL generation: **Passed**.
- Docker Compose configuration: **Passed**.

## Priority 3

- Optional audio extraction/quality, provider-independent transcription, anonymous diarization/roles, transcript corrections/search/exports, discourse/content, automated audited retention, enriched reports, context/reviewer-aware versioned fusion, Evidence Graph, settings/UI, and acceptance tests: **Complete**.
- Local diarization model execution remains deployment-dependent: the privacy-safe adapter and disabled/unavailable behavior are complete, but no heavyweight diarization dependency is installed by default.

## Priority 4

- Signed-token authentication with revocation, explicit development adapter, HTTP/WebSocket RBAC and resource isolation, user lifecycle management, classroom/course ownership and membership, aggregate dashboards, comparison warnings, UTC trend buckets and rolling averages, advanced evidence filters, deduplicated advisory notifications, optimistic-lock notes, audit trail, CSV/JSON/PDF aggregate exports, permission-aware management/analytics workspaces, migration, and security/regression tests: **Complete**.
- Institution-managed OIDC/SSO federation remains deployment-specific; the signed-token provider is the supported built-in production authentication option.
- Built-in production authentication uses expiring signed tokens; institution-managed OIDC/SSO federation remains an optional deployment adapter rather than an acceptance dependency.
- The pre-Alembic local `ambisense.db` has no version stamp. Back it up and stamp the matching legacy revision before applying upgrades; new managed deployments must provision the documented baseline schema first.

## Later priorities

- Priority 5 (RBAC, privacy ledger, retention jobs beyond test cleanup, model evaluation, Celery/Redis, hardening): **Not started**.

Optional legacy fire, projector, face, and noise integrations remain preserved.
