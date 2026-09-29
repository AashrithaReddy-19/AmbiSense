"""Processing job runners.

``InProcessJobRunner`` preserves the existing local behaviour: the job runs in
the API process after the response is sent (FastAPI ``BackgroundTasks``, or a
daemon thread when no ``BackgroundTasks`` is supplied). It is appropriate for
local and demo use only - jobs die with the process and are not durable.

Job *state* is durable regardless of the runner because it lives on the
``sessions`` row (``status``, ``processing_stage``, ``job_id``, ``retry_count``,
``failure_code``). ``QueueJobRunner`` documents the interface an external
broker (Celery/RQ/Arq/...) would implement; no broker is bundled.
"""
import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from .. import models
from ..timeutil import utc_now_naive

logger = logging.getLogger("ambisense.jobs")

# Sessions in these states are owned by a running worker (or a finished job).
CLAIMED_STATES = ("DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "INITIALIZING", "FINALIZING", "COMPLETED")
ACTIVE_JOB_STATES = ("QUEUED", "DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT")
RETRYABLE_STATES = ("FAILED",)


def claim_job(db, session_id: int) -> bool:
    """Atomically take ownership of a job that no worker owns (not decoding/processing/completed), so two workers can never run it twice."""
    result = db.execute(update(models.Session).where(models.Session.id == session_id, models.Session.status.notin_(CLAIMED_STATES)).values(status="DECODING", processing_stage="DECODING"))
    db.commit()
    return result.rowcount == 1


def claim_retry(db, session_id: int) -> bool:
    """Atomically requeue a FAILED job. Concurrent retries: exactly one wins (idempotent)."""
    result = db.execute(update(models.Session).where(models.Session.id == session_id, models.Session.status.in_(RETRYABLE_STATES)).values(status="QUEUED", processing_stage="QUEUED", progress=0, processed_frames=0, error=None, failure_code=None, retry_count=models.Session.retry_count + 1))
    db.commit()
    return result.rowcount == 1


def upsert_report(db, session_id: int, report_format: str, path) -> models.Report:
    """Insert or update the single Report row per (session, format); never duplicates."""
    row = db.scalar(select(models.Report).where(models.Report.session_id == session_id, models.Report.format == report_format))
    if row:
        row.path = str(path)
        return row
    try:
        with db.begin_nested():
            row = models.Report(session_id=session_id, format=report_format, path=str(path))
            db.add(row)
            db.flush()
    except Exception:
        # A concurrent writer created it first (UNIQUE session_id+format): reuse theirs.
        row = db.scalar(select(models.Report).where(models.Report.session_id == session_id, models.Report.format == report_format))
        if row is None:
            raise
        row.path = str(path)
    return row


# In-process ownership: which sessions a live worker / live camera socket in THIS process is handling right now.
_live_connections: set[int] = set()
_live_lock = threading.Lock()

VIDEO_RUNNING_STATES = ("DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT")
LIVE_RUNNING_STATES = ("INITIALIZING", "PROCESSING", "FINALIZING")
QUEUED_GRACE = timedelta(minutes=5)  # a job may legitimately sit QUEUED for a moment while it is dispatched
STALE_EXPLANATION = ("Jobs run inside the API process, so work that was in progress when the server stopped or restarted cannot continue. "
                     "These sessions still claim to be running but nothing is processing them.")


def live_connection_opened(session_id: int) -> None:
    with _live_lock:
        _live_connections.add(session_id)


def live_connection_closed(session_id: int) -> None:
    with _live_lock:
        _live_connections.discard(session_id)


def _live_connected(session_id: int) -> bool:
    with _live_lock:
        return session_id in _live_connections


def _age_minutes(row, now: datetime) -> float:
    since = row.started_at or row.created_at
    return round(max(0.0, (now - since).total_seconds() / 60), 1) if since else 0.0


STALE_KIND_REASONS = {
    "STALE_VIDEO_JOB": "No worker is processing this video job. Marking it failed lets you retry it.",
    "LIVE_CAPTURE_INTERRUPTED": "The live camera connection ended without a clean stop. A live capture cannot be resumed, so this session is left unchanged.",
}


def stale_kind(session_id: int, status: str, source_type: str, created_at, runner, now: datetime) -> str | None:
    """The single rule for "this session claims to be running but nothing is running it" (None if it is fine).

    A video job counts when it is in a running state (or QUEUED past a short grace period) and no worker in this process
    owns it. A live session counts when it is in a running state with no open camera connection."""
    if source_type == "VIDEO":
        if status in VIDEO_RUNNING_STATES and not runner.owns(session_id):
            return "STALE_VIDEO_JOB"
        if status == "QUEUED" and not runner.owns(session_id) and created_at is not None and now - created_at >= QUEUED_GRACE:
            return "STALE_VIDEO_JOB"
    elif source_type == "LIVE" and status in LIVE_RUNNING_STATES and not _live_connected(session_id):
        return "LIVE_CAPTURE_INTERRUPTED"
    return None


def stale_job_report(db, runner=None, now: datetime | None = None) -> dict:
    """Read-only. Sessions that claim to be running although no worker in this process owns them.

    - ``STALE_VIDEO_JOB``: recoverable - it can be marked FAILED and retried.
    - ``LIVE_CAPTURE_INTERRUPTED``: reported for information only; a live capture cannot be resumed and recovery never changes it.
    Anything owned by a worker or connection that exists right now is never listed.
    """
    now = now or utc_now_naive()
    runner = runner or get_job_runner()
    items = []
    candidates = select(models.Session).where(models.Session.status.in_(VIDEO_RUNNING_STATES + LIVE_RUNNING_STATES + ("QUEUED",))).order_by(models.Session.id)
    for row in db.scalars(candidates).all():
        kind = stale_kind(row.id, row.status, row.source_type, row.created_at, runner, now)
        if kind is None:
            continue
        items.append({"id": row.id, "name": row.name, "source_type": row.source_type, "status": row.status, "processing_stage": row.processing_stage, "progress": row.progress,
                      "started_at": row.started_at, "created_at": row.created_at, "age_minutes": _age_minutes(row, now), "kind": kind,
                      "recoverable": kind == "STALE_VIDEO_JOB", "reason": STALE_KIND_REASONS[kind]})
    stopped = {status: db.scalar(select(func.count(models.Session.id)).where(models.Session.status == status)) or 0 for status in ("STOPPED", "CREATED")}
    recoverable = [item for item in items if item["recoverable"]]
    return {"explanation": STALE_EXPLANATION, "runner": {"mode": runner.mode, "durable": False}, "total": len(items), "recoverable": len(recoverable), "items": items,
            "not_running": {"STOPPED": stopped["STOPPED"], "CREATED": stopped["CREATED"], "note": "STOPPED and CREATED sessions are not running jobs and are not treated as stale."}}


def recover_interrupted_jobs(db, reason: str = "The API process stopped while this job was running.", session_ids: list[int] | None = None, actor_user_id: int | None = None, runner=None) -> list[int]:
    """Mark stale VIDEO jobs as FAILED (retryable). Only an explicit, confirmed administrator action (or a test) calls this;
    it never runs at startup. ``session_ids`` narrows it to a selection. Idempotent: a session already FAILED is no longer
    stale, so a repeated call changes nothing and writes no audit entry."""
    wanted = set(session_ids) if session_ids is not None else None
    recovered = []
    for item in stale_job_report(db, runner)["items"]:
        if not item["recoverable"] or (wanted is not None and item["id"] not in wanted):
            continue
        # Conditional update so a job that finished (or was claimed) between the report and now is left alone.
        result = db.execute(update(models.Session).where(models.Session.id == item["id"], models.Session.status == item["status"])
                            .values(status="FAILED", processing_stage="FAILED", failure_code="JOB_INTERRUPTED", error=reason, ended_at=utc_now_naive()))
        if result.rowcount != 1:
            continue
        db.add(models.AuditEntry(actor_user_id=actor_user_id, action="JOB_RECOVERED", resource_type="SESSION", resource_id=item["id"], details={"failure_code": "JOB_INTERRUPTED", "previous_status": item["status"], "previous_stage": item["processing_stage"]}))
        recovered.append(item["id"])
    db.commit()
    return recovered


class JobRunner(ABC):
    mode: str

    def owns(self, session_id: int) -> bool:
        """True while a worker of this runner is processing the session right now."""
        return False

    @abstractmethod
    def dispatch(self, session_id: int, video_path: str, settings, background_tasks=None) -> None:
        """Start (or enqueue) processing for a session that is already QUEUED."""

    @abstractmethod
    def health(self, db) -> dict:
        """Worker health without side effects."""


class InProcessJobRunner(JobRunner):
    mode = "IN_PROCESS"

    def __init__(self) -> None:
        self._active = 0
        self._active_ids: set[int] = set()
        self._lock = threading.Lock()
        self.last_started_at: datetime | None = None

    def _run(self, session_id: int, video_path: str, settings) -> None:
        from .video_processor import VideoProcessor  # deferred: pulls in torch/cv2

        with self._lock:
            self._active += 1
            self._active_ids.add(session_id)
            self.last_started_at = utc_now_naive()
        try:
            VideoProcessor(session_id, video_path, settings).run()
        finally:
            with self._lock:
                self._active -= 1
                self._active_ids.discard(session_id)

    def owns(self, session_id: int) -> bool:
        with self._lock:
            return session_id in self._active_ids

    def dispatch(self, session_id: int, video_path: str, settings, background_tasks=None) -> None:
        if background_tasks is not None:
            background_tasks.add_task(self._run, session_id, video_path, settings)
        else:
            threading.Thread(target=self._run, args=(session_id, video_path, settings), daemon=True, name=f"ambisense-job-{session_id}").start()

    def health(self, db) -> dict:
        queued = db.scalar(select(func.count(models.Session.id)).where(models.Session.status == "QUEUED")) or 0
        in_flight = db.scalar(select(func.count(models.Session.id)).where(models.Session.source_type == "VIDEO", models.Session.status.in_(VIDEO_RUNNING_STATES))) or 0
        with self._lock:
            active = self._active
        # Rows claiming to run with no worker in this process => orphaned by an earlier crash/restart.
        stale = sum(1 for item in stale_job_report(db, self)["items"] if item["recoverable"])
        return {"mode": self.mode, "durable": False, "healthy": True, "workers_active": active, "queue_depth": queued, "jobs_in_flight": in_flight, "stale_jobs": stale, "note": "In-process jobs are for local/demo use; they do not survive a restart."}


class QueueJobRunner(JobRunner):
    """Interface for an external durable queue. Intentionally not implemented here."""

    mode = "QUEUE"

    def dispatch(self, session_id: int, video_path: str, settings, background_tasks=None) -> None:
        raise NotImplementedError("QueueJobRunner requires an external broker adapter; none is bundled.")

    def health(self, db) -> dict:
        return {"mode": self.mode, "durable": True, "healthy": False, "note": "No queue adapter is configured."}


_runner: JobRunner | None = None


def get_job_runner(settings=None) -> JobRunner:
    global _runner
    if _runner is None:
        from ..config import get_settings

        mode = (settings or get_settings()).job_runner_mode.upper()
        if mode == "QUEUE":
            raise RuntimeError("JOB_RUNNER_MODE=QUEUE is not available: no queue adapter is bundled. Use IN_PROCESS for local/demo use.")
        _runner = InProcessJobRunner()
    return _runner
