# Privacy and ethics

AmbiSense is an aggregate, privacy-conscious research prototype. It **does not identify people**, infer protected
traits, rank students, or support academic or disciplinary decisions.

## What is and is not collected

- **No facial recognition, no face embeddings, no identity storage, no cross-session matching.** Face landmarks are used transiently to compute geometric signals (head direction, eye/mouth ratios); raw face crops are not stored.
- Tracks are **anonymous and session-local**: an ID has no meaning outside its session.
- **Occupancy is an estimate and is not verified attendance.** There is no attendance record, and no UI text or report says otherwise.
- Videos you upload (and the annotated copies) are stored on the server until an authorised person deletes them. Audio, transcripts and lecture content exist **only** if an operator enables the optional audio features; speakers are anonymous roles and are never identified.

## Statements shown in the product

Wherever evidence is displayed the interface shows:

> AmbiSense uses anonymous session-local tracking and does not identify students.
> Occupancy is an estimate and is not verified attendance.
> These observational indicators must not be used as the sole basis for grading, discipline, attendance, or other high-impact decisions.

and, on Settings, reports and the API status endpoint:

> Not validated on real classroom footage. No verified accuracy or fairness result is currently available.

## Wording rules

Preferred: *anonymous occupancy estimate, visual-orientation estimate, observable participation indicator, possible
prolonged eye closure, possible fatigue indicator, raised-hand observation, insufficient evidence, unavailable.*
Avoided: verified attendance, "student is attentive/disengaged/sleeping", emotion detected, student performance, cheating detected.
Reports, the interface and the metric definitions follow these rules, and automated tests check the wording of the
definitions and the required notices. (A legacy column named `verified_attendance_rate` still exists in the CSV/JSON
schema for backward compatibility; it is always empty and is not shown in the interface or the PDF.)

## Every metric explains itself

For each metric the application states its meaning, required evidence, coverage, confidence, why it can be
unavailable, limitations and applicable activity contexts (*Metric definitions and limitations*; [docs/METRICS.md](docs/METRICS.md)).

## Retention and deletion

| Control | Behaviour |
|---|---|
| Session retention (`RETENTION_DAYS`) | Sessions older than the period are *offered for archiving* (hidden, reversible, evidence kept). Nothing is deleted automatically. |
| Permanent session deletion | Explicit per-session action; requires typing DELETE in the UI and `confirm=true` on the API; removes all dependent rows and the session's files; written to the audit trail. Active sessions cannot be deleted. |
| Artifact deletion | Removes selected files (original/annotated video, reports, audio, transcript exports) and keeps analytics evidence; confirmed and audited. |
| Transcript/audio retention | Automatic after `TRANSCRIPT_RETENTION_DAYS`; aggregates are preserved. |
| Test-data cleanup | Archives or deletes only sessions explicitly flagged as tests, after a configured age. |
| Files outside the managed directories | Never deleted, even if a database row points at them. |

Backups keep what they held when taken; see [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

## Responsibilities of the operator

Obtain consent and define a lawful purpose before recording; restrict access (enable authentication and roles); give
notice of cameras/audio; define retention; keep a human in every decision; and do not use these indicators for
grading, discipline, attendance or performance evaluation. Visual estimates are affected by lighting, camera angle,
occlusion, distance, demographics and context, and have **not** been evaluated for fairness.

## Access, roles and audit

Roles (administrator, instructor, reviewer, viewer) and classroom/course membership are enforced on the server.
Sensitive changes (roles, deactivation, settings, deletion, retention, layout saves) are recorded in the audit trail.
Diagnostics and logs never contain passwords, tokens, raw frames, face crops or request bodies.
