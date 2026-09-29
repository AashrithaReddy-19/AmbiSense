"""Production-hardening tests: error contract, request IDs, readiness/diagnostics,
configuration validation, rate limiting and upload security."""
import io
import os
import tempfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import models
from backend.app.config import ROOT_DIR, Settings, get_settings
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app, sanitize_filename
from backend.app.services.startup_checks import ConfigurationError, enforce_settings, validate_settings

Base.metadata.create_all(engine)
settings = get_settings()


def _tiny_video_bytes() -> bytes:
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (32, 32))
        for _ in range(5):
            writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
        writer.release()
        with open(path, "rb") as stream:
            return stream.read()
    finally:
        os.unlink(path)


def _upload_dir_files() -> set[str]:
    return {entry.name for entry in settings.upload_dir.iterdir() if entry.is_file()}


# --- Error contract and request IDs -------------------------------------------------

def test_not_found_uses_canonical_error_and_keeps_legacy_detail():
    with TestClient(app) as client:
        response = client.get("/api/sessions/99999999")
        assert response.status_code == 404
        body = response.json()
        assert body["detail"] == "Session not found"
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"] == "Session not found"
        assert body["error"]["request_id"] == response.headers["X-Request-ID"]


def test_structured_errors_keep_their_specific_code_and_gain_request_id():
    with TestClient(app) as client:
        response = client.get("/api/v1/sessions?minimum_coverage=2")
        body = response.json()
        assert body["error"]["code"] == "INVALID_COVERAGE"
        assert body["detail"]["error"]["code"] == "INVALID_COVERAGE"
        assert body["error"]["request_id"]


def test_well_formed_request_id_is_echoed_and_malformed_is_replaced():
    with TestClient(app) as client:
        assert client.get("/api/health", headers={"X-Request-ID": "trace-abc-12345"}).headers["X-Request-ID"] == "trace-abc-12345"
        replaced = client.get("/api/health", headers={"X-Request-ID": "bad id with spaces!"}).headers["X-Request-ID"]
        assert replaced != "bad id with spaces!" and len(replaced) == 32


def test_validation_errors_do_not_echo_submitted_values():
    with TestClient(app) as client:
        response = client.post("/api/v1/analytics/compare", json={"session_ids": [1], "metrics": ["secret-value-xyz"]})
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_FAILED"
        assert "secret-value-xyz" not in response.text
        assert isinstance(body["detail"], list)


@app.get("/__test_boom")
def _boom():  # registered only by the test module; proves the 500 handler hides internals
    raise RuntimeError("secret internals")


def test_unhandled_exception_returns_generic_500_with_reference():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test_boom", headers={"X-Request-ID": "boom-request-1"})
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["request_id"] == "boom-request-1"
        assert "secret internals" not in response.text


# --- Health / readiness / diagnostics ------------------------------------------------

def test_health_is_lightweight_and_does_not_touch_the_database():
    with TestClient(app) as client:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert set(body) >= {"device", "demo_mode", "max_upload_mb"}


def test_ready_reports_checks_and_fails_when_models_missing(monkeypatch):
    with TestClient(app) as client:
        good = client.get("/api/ready")
        assert good.status_code == 200 and good.json()["status"] == "ready"
        assert set(good.json()["checks"]) == {"database", "models", "storage", "job_runner"}
        monkeypatch.setattr(settings, "yolo_model", "definitely-missing-weights.pt")
        bad = client.get("/api/ready")
        assert bad.status_code == 503
        assert bad.json()["status"] == "not_ready"
        assert bad.json()["checks"]["models"]["ok"] is False


def test_diagnostics_never_expose_secrets_paths_or_sql(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret_key", "super-secret-diagnostics-value-1234567890")
    with TestClient(app) as client:
        text = client.get("/api/v1/system/diagnostics").text
        assert "super-secret-diagnostics-value" not in text
        assert ROOT_DIR.as_posix() not in text and str(ROOT_DIR) not in text
        assert "sqlite:///" not in text and "SELECT" not in text
        body = client.get("/api/v1/system/diagnostics").json()
        assert body["database"]["dialect"] == "sqlite"
        assert body["worker"]["mode"] == "IN_PROCESS" and body["worker"]["durable"] is False


# --- Configuration validation ---------------------------------------------------------

def _settings(**overrides) -> Settings:
    base = dict(database_url="sqlite:///" + (ROOT_DIR / "x.db").as_posix(), upload_dir=settings.upload_dir, report_dir=settings.report_dir, log_dir=settings.log_dir, classroom_reference_dir=settings.classroom_reference_dir, demo_mode=True)
    base.update(overrides)
    return Settings(**base)


def _codes(issues, level):
    return {issue.setting for issue in issues if issue.level == level}


def test_valid_configuration_has_no_errors():
    assert not _codes(validate_settings(_settings()), "ERROR")


@pytest.mark.parametrize("overrides, setting", [
    ({"database_url": "mysql://nope"}, "DATABASE_URL"),
    ({"cors_origins": "*"}, "CORS_ORIGINS"),
    ({"cors_origins": "localhost:5173"}, "CORS_ORIGINS"),
    ({"auth_enabled": True, "auth_mode": "TOKEN", "auth_secret_key": "short"}, "AUTH_SECRET_KEY"),
    ({"max_upload_mb": 0}, "MAX_UPLOAD_MB"),
    ({"max_video_duration_minutes": 0}, "MAX_VIDEO_DURATION_MINUTES"),
    ({"retention_days": 0}, "RETENTION_DAYS"),
    ({"test_session_cleanup_action": "SHRED"}, "TEST_SESSION_CLEANUP_ACTION"),
    ({"log_level": "LOUD"}, "LOG_LEVEL"),
    ({"rate_limit_backend": "redis"}, "REDIS_URL"),
    ({"job_runner_mode": "QUEUE"}, "JOB_RUNNER_MODE"),
])
def test_invalid_configuration_is_reported_with_the_setting_name(overrides, setting):
    assert setting in _codes(validate_settings(_settings(**overrides)), "ERROR")


def test_unwritable_directory_is_an_error(tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    assert "UPLOAD_DIR" in _codes(validate_settings(_settings(upload_dir=blocker / "sub")), "ERROR")


def test_enforce_raises_actionable_error_without_leaking_values():
    with pytest.raises(ConfigurationError) as caught:
        enforce_settings(_settings(auth_enabled=True, auth_mode="TOKEN", auth_secret_key="tiny-secret"))
    assert "AUTH_SECRET_KEY" in str(caught.value) and "tiny-secret" not in str(caught.value)


def test_development_auth_mode_warns_instead_of_failing_on_short_secret():
    issues = validate_settings(_settings(auth_enabled=True, auth_mode="DEVELOPMENT", auth_secret_key=""))
    assert "AUTH_SECRET_KEY" in _codes(issues, "WARNING") and "AUTH_SECRET_KEY" not in _codes(issues, "ERROR")


# --- Rate limiting ---------------------------------------------------------------------

def test_search_rate_limit_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_search_per_minute", 2)
    with TestClient(app) as client:
        for _ in range(2):
            assert client.post("/api/search", json={"query": "engagement below 50"}).status_code == 200
        blocked = client.post("/api/search", json={"query": "engagement below 50"})
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert int(blocked.headers["Retry-After"]) >= 1


def test_login_and_upload_and_report_and_analytics_are_limited(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_analytics_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_report_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_upload_per_minute", 1)
    with TestClient(app) as client:
        credentials = {"email": "nobody@example.test", "password": "x"}
        assert client.post("/api/v1/auth/login", json=credentials).status_code == 401
        assert client.post("/api/v1/auth/login", json=credentials).status_code == 429
        assert client.get("/api/v1/analytics/trends").status_code == 200
        assert client.get("/api/v1/analytics/trends").status_code == 429
        assert client.get("/api/v1/reports").status_code == 200
        assert client.get("/api/v1/reports").status_code == 429
        assert client.post("/api/uploads", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 415
        assert client.post("/api/uploads", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 429


def test_rate_limiting_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_search_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    with TestClient(app) as client:
        assert all(client.post("/api/search", json={"query": "engagement below 50"}).status_code == 200 for _ in range(4))


def test_in_memory_limiter_window_and_reset():
    from backend.app.services.rate_limit import InMemoryRateLimiter

    limiter = InMemoryRateLimiter()
    assert [limiter.hit("k", 2)[0] for _ in range(3)] == [True, True, False]
    assert limiter.hit("other", 2)[0] is True
    limiter.reset()
    assert limiter.hit("k", 2)[0] is True


# --- Upload security -----------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [("../../evil.mp4", "evil.mp4"), ("..\\..\\evil.mp4", "evil.mp4"), ("a<b>c|d.mp4", "a_b_c_d.mp4"), ("   ..  ", "upload"), (None, "upload"), ("ok name (1).mp4", "ok name (1).mp4")])
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_upload_stores_random_name_and_sanitized_display_name():
    before = _upload_dir_files()
    with TestClient(app) as client:
        response = client.post("/api/uploads", files={"file": ("../../evil name.mp4", io.BytesIO(_tiny_video_bytes()), "video/mp4")}, data={"name": "Security upload", "activity_context": "lecture"})
        assert response.status_code == 200, response.text
        body = response.json()
    assert body["source_filename"] == "evil name.mp4"
    assert body["activity_context"] == "LECTURE"
    created = _upload_dir_files() - before
    assert len(created) == 1
    stored = next(iter(created))
    assert "evil" not in stored and stored.endswith(".mp4") and len(stored) == 36


@pytest.mark.parametrize("filename, content, mime, status, code", [
    ("clip.exe", b"MZ", "application/octet-stream", 415, "UNSUPPORTED_VIDEO_FORMAT"),
    ("clip.mp4", b"x", "text/html", 415, "UNSUPPORTED_MIME_TYPE"),
    ("clip.mp4", b"", "video/mp4", 422, "EMPTY_FILE"),
    ("clip.mp4", b"this is not a video at all", "video/mp4", 422, "VIDEO_DECODING_FAILED"),
])
def test_rejected_uploads_leave_no_orphan_file(filename, content, mime, status, code):
    before = _upload_dir_files()
    with TestClient(app) as client:
        response = client.post("/api/uploads", files={"file": (filename, io.BytesIO(content), mime)})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert _upload_dir_files() == before


def test_oversized_upload_is_rejected_and_cleaned_up(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    before = _upload_dir_files()
    with TestClient(app) as client:
        response = client.post("/api/uploads", files={"file": ("big.mp4", io.BytesIO(b"0" * (1024 * 1024 + 10)), "video/mp4")})
    assert response.status_code == 413 and response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert _upload_dir_files() == before


def test_upload_rejects_unknown_activity_context_and_bad_names():
    with TestClient(app) as client:
        video = _tiny_video_bytes()
        bad_context = client.post("/api/uploads", files={"file": ("a.mp4", io.BytesIO(video), "video/mp4")}, data={"activity_context": "PARTY"})
        assert bad_context.status_code == 422 and bad_context.json()["error"]["code"] == "INVALID_ACTIVITY_CONTEXT"
        too_long = client.post("/api/uploads", files={"file": ("a.mp4", io.BytesIO(video), "video/mp4")}, data={"name": "n" * 200})
        assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "INVALID_SESSION_NAME"


def test_video_endpoint_refuses_files_outside_managed_directories(tmp_path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not for download")
    with SessionLocal() as db:
        row = models.Session(name="Path traversal check", status="COMPLETED", video_path=str(outside))
        db.add(row); db.commit()
        session_id = row.id
    with TestClient(app) as client:
        assert client.get(f"/api/sessions/{session_id}/video?annotated=false").status_code == 404
