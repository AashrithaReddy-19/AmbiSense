"""Lightweight rate limiting.

``InMemoryRateLimiter`` is a fixed-window counter suitable for one local
process (development, demo, tests). It is *not* shared between workers or
restarts. ``RedisRateLimiter`` implements the same interface for multi-worker
production deployments; it needs the optional ``redis`` package and a
``REDIS_URL`` and has not been exercised against a live Redis in this
repository's automated tests.
"""
import threading
import time
from typing import Protocol

from fastapi import Request

from ..config import get_settings
from ..errors import structured_error

BUCKET_SETTINGS = {
    "login": "rate_limit_login_per_minute",
    "upload": "rate_limit_upload_per_minute",
    "search": "rate_limit_search_per_minute",
    "analytics": "rate_limit_analytics_per_minute",
    "report": "rate_limit_report_per_minute",
}
WINDOW_SECONDS = 60


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window: int = WINDOW_SECONDS) -> tuple[bool, int]:
        """Record a request; return (allowed, retry_after_seconds)."""


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int = WINDOW_SECONDS) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            started, count = self._windows.get(key, (now, 0))
            if now - started >= window:
                started, count = now, 0
            count += 1
            self._windows[key] = (started, count)
            if len(self._windows) > 10_000:  # bound memory: drop expired windows
                self._windows = {k: v for k, v in self._windows.items() if now - v[0] < window}
            return count <= limit, max(1, int(window - (now - started)))

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        import redis  # optional production dependency

        self._client = redis.Redis.from_url(url, socket_timeout=1)

    def hit(self, key: str, limit: int, window: int = WINDOW_SECONDS) -> tuple[bool, int]:
        redis_key = f"ambisense:ratelimit:{key}"
        count = self._client.incr(redis_key)
        if count == 1:
            self._client.expire(redis_key, window)
        ttl = self._client.ttl(redis_key)
        return count <= limit, max(1, int(ttl if ttl and ttl > 0 else window))


_memory = InMemoryRateLimiter()
_backend: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    global _backend
    if _backend is None:
        settings = get_settings()
        if settings.rate_limit_backend.lower() == "redis":
            _backend = RedisRateLimiter(settings.redis_url)
        else:
            _backend = _memory
    return _backend


def reset_rate_limits() -> None:
    """Clear in-memory counters (used by tests and the admin console)."""
    _memory.reset()


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit(bucket: str):
    """FastAPI dependency: ``dependencies=[Depends(limit("search"))]``."""
    setting_name = BUCKET_SETTINGS[bucket]

    def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        allowed, retry_after = get_limiter().hit(f"{bucket}:{_client_key(request)}", int(getattr(settings, setting_name)))
        if not allowed:
            raise structured_error(429, "RATE_LIMITED", f"Too many {bucket} requests. Try again in {retry_after} seconds.", {"bucket": bucket, "retry_after_seconds": retry_after}, {"Retry-After": str(retry_after)})

    return dependency
