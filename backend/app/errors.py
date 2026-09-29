"""Consistent error contract and request-ID propagation.

Every error response carries both the legacy ``detail`` member (kept so
existing clients and tests keep working) and a canonical ``error`` object::

    {"detail": ..., "error": {"code", "message", "details", "request_id"}}

Request IDs are accepted from a well-formed ``X-Request-ID`` header or
generated, echoed in the response header, attached to every log record, and
included in error bodies so a user-visible reference can be matched to logs.
Query strings are never logged (WebSocket URLs can carry access tokens).
"""
import logging
import re
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
STATUS_ERROR_CODES = {
    400: "BAD_REQUEST", 401: "AUTHENTICATION_REQUIRED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_FAILED", 429: "RATE_LIMITED", 500: "INTERNAL_ERROR", 503: "SERVICE_UNAVAILABLE",
}
logger = logging.getLogger("ambisense.http")


class RequestIdFilter(logging.Filter):
    """Adds ``request_id`` to every record so the log format can reference it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def structured_error(status_code: int, code: str, message: str, details=None, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code, {"error": {"code": code, "message": message, "details": details}}, headers=headers)


def error_body(status_code: int, detail, request_id: str | None = None) -> dict:
    """Build the canonical error body for any HTTPException ``detail``."""
    request_id = request_id or request_id_var.get()
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        inner = detail["error"]
        error = {"code": inner.get("code") or STATUS_ERROR_CODES.get(status_code, "ERROR"), "message": inner.get("message", ""), "details": inner.get("details"), "request_id": request_id}
    else:
        message = detail if isinstance(detail, str) else "Request failed."
        error = {"code": STATUS_ERROR_CODES.get(status_code, "ERROR"), "message": message, "details": None if isinstance(detail, str) else jsonable_encoder(detail), "request_id": request_id}
    return {"detail": detail, "error": error}


def error_response(status_code: int, detail, headers: dict | None = None) -> JSONResponse:
    response = JSONResponse(error_body(status_code, detail), status_code=status_code, headers=headers)
    response.headers["X-Request-ID"] = request_id_var.get()
    return response


def install_error_handling(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        return error_response(exc.status_code, exc.detail, dict(exc.headers or {}) or None)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        # Field locations and messages only; submitted values are never echoed back.
        problems = [{"loc": list(item.get("loc", [])), "message": item.get("msg", ""), "type": item.get("type", "")} for item in exc.errors()]
        body = error_body(422, "Request validation failed.")
        body["detail"] = jsonable_encoder([{"loc": p["loc"], "msg": p["message"], "type": p["type"]} for p in problems])
        body["error"].update({"code": "VALIDATION_FAILED", "details": problems})
        response = JSONResponse(body, status_code=422)
        response.headers["X-Request-ID"] = request_id_var.get()
        return response

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception):
        logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path, exc_info=exc)
        # Runs in ServerErrorMiddleware, outside the request-ID middleware's context variable.
        reference = getattr(request.state, "request_id", None) or request_id_var.get()
        body = {"detail": "Internal server error", "error": {"code": "INTERNAL_ERROR", "message": f"An unexpected error occurred. Reference: {reference}", "details": None, "request_id": reference}}
        response = JSONResponse(body, status_code=500)
        response.headers["X-Request-ID"] = reference
        return response

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _REQUEST_ID_PATTERN.match(supplied) else uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Starlette's ServerErrorMiddleware re-raises after answering; keep the trace linked to this ID.
            logger.error("Request failed %s %s: %s", request.method, request.url.path, type(exc).__name__)
            raise
        else:
            response.headers["X-Request-ID"] = request_id
            if request.url.path.startswith("/api/"):
                logger.info("%s %s -> %s in %.1fms", request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
            return response
        finally:
            request_id_var.reset(token)
