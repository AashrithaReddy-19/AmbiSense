"""Single source of truth for "now" and UTC normalisation.

Storage convention: database columns are timezone-naive `DateTime` holding UTC, and existing rows already follow it, so
values written to or compared with the database use `utc_now_naive()`. Timestamps that leave the process on the wire
(JSON payloads, generated-at stamps) use the timezone-aware `utc_now()`. `as_utc()` makes either kind safe to compare.

`datetime.utcnow()` is deprecated and must not be used; both helpers are built on `datetime.now(timezone.utc)`.
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime, matching how the database columns store values."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc(value: datetime) -> datetime:
    """Return `value` as a timezone-aware UTC datetime; a naive value is assumed to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def as_naive_utc(value: datetime) -> datetime:
    """Return `value` as a naive UTC datetime (the database convention)."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utc_iso_z(value: datetime | None = None) -> str:
    """ISO-8601 UTC string with a trailing `Z`, for wire payloads."""
    return as_utc(value or utc_now()).isoformat().replace("+00:00", "Z")
