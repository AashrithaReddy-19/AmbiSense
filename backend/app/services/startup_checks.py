"""Configuration validation and readiness probes.

``validate_settings`` returns actionable issues; ERROR-level issues make the
API refuse to start (fail safe), WARNING-level issues are logged and shown in
diagnostics. Nothing here ever includes secrets or absolute production paths
in its messages - only setting *names* and safe hints.
"""
import importlib.util
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

logger = logging.getLogger("ambisense.config")
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True)
class ConfigIssue:
    level: str  # ERROR | WARNING
    setting: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


class ConfigurationError(RuntimeError):
    def __init__(self, issues: list[ConfigIssue]):
        self.issues = issues
        super().__init__("Invalid AmbiSense configuration:\n" + "\n".join(f"  - {issue.setting}: {issue.message}" for issue in issues))


def directory_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".write-check-", delete=True):
            pass
        return True
    except OSError:
        return False


def _valid_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.path.strip("/")


def validate_settings(settings) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    error = lambda name, message: issues.append(ConfigIssue("ERROR", name, message))
    warn = lambda name, message: issues.append(ConfigIssue("WARNING", name, message))

    url = settings.database_url
    if not url.startswith(("sqlite:///", "postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        error("DATABASE_URL", "Use sqlite:///<file> or postgresql+psycopg://user:password@host:5432/dbname.")
    elif url.startswith("sqlite:///") and ":memory:" not in url:
        database_file = Path(url.removeprefix("sqlite:///"))
        if not database_file.parent.exists():
            error("DATABASE_URL", "The SQLite database directory does not exist; create it or fix the path.")

    origins = settings.cors_origin_list
    if not origins:
        warn("CORS_ORIGINS", "No allowed origins are configured; browsers on other origins cannot call the API.")
    for origin in origins:
        if origin == "*":
            error("CORS_ORIGINS", "A wildcard origin is not allowed because the API allows credentials; list explicit origins.")
        elif not _valid_origin(origin):
            error("CORS_ORIGINS", f"'{origin}' is not a valid origin. Use scheme://host[:port] with no path.")

    if settings.trusted_host_list == ["*"] and settings.auth_enabled:
        warn("TRUSTED_HOSTS", "Trusted hosts are unrestricted while authentication is enabled; set TRUSTED_HOSTS to your public host names.")

    if settings.auth_enabled:
        if len(settings.auth_secret_key) < 32:
            # Only TOKEN mode depends on signed tokens; DEVELOPMENT mode identifies callers by header instead.
            (error if settings.auth_mode.upper() == "TOKEN" else warn)("AUTH_SECRET_KEY", "AUTH_SECRET_KEY is shorter than 32 characters; signed tokens cannot be issued.")
        if settings.auth_mode.upper() not in {"TOKEN", "DEVELOPMENT"}:
            error("AUTH_MODE", "AUTH_MODE must be TOKEN or DEVELOPMENT.")
        elif settings.auth_mode.upper() == "DEVELOPMENT":
            warn("AUTH_MODE", "DEVELOPMENT mode trusts the X-User-Id header; never use it on a reachable network.")
        if settings.auth_access_token_expire_minutes < 1:
            error("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "Token lifetime must be at least one minute.")
    else:
        warn("AUTH_ENABLED", "Authentication is disabled: every caller acts as a local administrator. Development use only.")

    for name, folder in (("UPLOAD_DIR", settings.upload_dir), ("REPORT_DIR", settings.report_dir), ("LOG_DIR", settings.log_dir), ("CLASSROOM_REFERENCE_DIR", settings.classroom_reference_dir)):
        if not directory_writable(Path(folder)):
            error(name, "The directory is not writable; fix permissions or the path.")

    if not settings.demo_mode:
        if not Path(settings.yolo_model).exists() and importlib.util.find_spec("ultralytics") is None:
            error("YOLO_MODEL", "The detector weights were not found and ultralytics is not installed; real processing cannot run.")
        elif not Path(settings.yolo_model).exists():
            warn("YOLO_MODEL", "The detector weights file was not found in the working directory; the library may try to download it.")
        for name, path in (("FACE_LANDMARKER_MODEL", settings.face_landmarker_model), ("POSE_LANDMARKER_MODEL", settings.pose_landmarker_model)):
            if not Path(path).exists():
                warn(name, "Model file not found; the related signals will be reported as unavailable (MODEL_DISABLED).")

    if not 1 <= settings.max_upload_mb <= 10240:
        error("MAX_UPLOAD_MB", "Must be between 1 and 10240.")
    if not 1 <= settings.max_video_duration_minutes <= 1440:
        error("MAX_VIDEO_DURATION_MINUTES", "Must be between 1 and 1440.")
    if not 1 <= settings.retention_days <= 3650:
        error("RETENTION_DAYS", "Must be between 1 and 3650.")
    if settings.transcript_retention_enabled and settings.transcript_retention_days < 1:
        error("TRANSCRIPT_RETENTION_DAYS", "Must be at least 1 while transcript retention is enabled.")
    if settings.test_session_cleanup_action.upper() not in {"ARCHIVE", "DELETE"}:
        error("TEST_SESSION_CLEANUP_ACTION", "Must be ARCHIVE or DELETE.")
    elif settings.test_session_cleanup_enabled and settings.test_session_cleanup_action.upper() == "DELETE":
        warn("TEST_SESSION_CLEANUP_ACTION", "DELETE permanently removes sessions flagged as tests after the configured age.")
    if settings.log_level.upper() not in VALID_LOG_LEVELS:
        error("LOG_LEVEL", "Must be DEBUG, INFO, WARNING, ERROR or CRITICAL.")
    if settings.rate_limit_backend.lower() not in {"memory", "redis"}:
        error("RATE_LIMIT_BACKEND", "Must be memory or redis.")
    elif settings.rate_limit_backend.lower() == "redis" and not settings.redis_url:
        error("REDIS_URL", "RATE_LIMIT_BACKEND=redis requires REDIS_URL.")
    if settings.job_runner_mode.upper() not in {"IN_PROCESS", "QUEUE"}:
        error("JOB_RUNNER_MODE", "Must be IN_PROCESS or QUEUE.")
    elif settings.job_runner_mode.upper() == "QUEUE":
        error("JOB_RUNNER_MODE", "QUEUE needs an external queue adapter that is not bundled; use IN_PROCESS.")
    return issues


def enforce_settings(settings) -> list[ConfigIssue]:
    issues = validate_settings(settings)
    for issue in issues:
        (logger.error if issue.level == "ERROR" else logger.warning)("config %s %s: %s", issue.level, issue.setting, issue.message)
    errors = [issue for issue in issues if issue.level == "ERROR"]
    if errors:
        raise ConfigurationError(errors)
    return issues


def readiness(db, settings, job_runner) -> dict:
    """Readiness checks; each entry is ``{"ok": bool, "detail": str}`` with no paths or secrets."""
    checks: dict[str, dict] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "detail": "Database reachable."}
    except Exception:
        checks["database"] = {"ok": False, "detail": "Database is unreachable."}
    if settings.demo_mode:
        checks["models"] = {"ok": True, "detail": "Demo mode: detector weights are not required."}
    else:
        has_weights = Path(settings.yolo_model).exists()
        has_library = importlib.util.find_spec("ultralytics") is not None
        checks["models"] = {"ok": has_weights and has_library, "detail": "Detector weights and library available." if has_weights and has_library else "Detector weights or the ultralytics library are missing."}
    writable = {name: directory_writable(Path(folder)) for name, folder in (("uploads", settings.upload_dir), ("reports", settings.report_dir), ("logs", settings.log_dir))}
    checks["storage"] = {"ok": all(writable.values()), "detail": "All artifact directories are writable." if all(writable.values()) else "Not writable: " + ", ".join(name for name, ok in writable.items() if not ok)}
    try:
        runner = job_runner.health(db)
        checks["job_runner"] = {"ok": bool(runner.get("healthy")), "detail": f"{runner.get('mode')} runner; {runner.get('stale_jobs', 0)} stale job(s).", "stale_jobs": runner.get("stale_jobs", 0)}
    except Exception:
        checks["job_runner"] = {"ok": False, "detail": "Job runner health could not be determined."}
    return {"status": "ready" if all(item["ok"] for item in checks.values()) else "not_ready", "checks": checks}
