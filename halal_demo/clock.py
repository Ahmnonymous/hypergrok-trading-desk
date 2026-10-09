"""Injectable clocks. Tests do not depend on the wall clock."""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


class FixedClock:
    def __init__(self, now: datetime):
        self._now = ensure_utc(now, "clock")

    def now(self) -> datetime:
        return self._now


def parse_utc(value: str, field: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} is not an ISO timestamp") from exc
    return ensure_utc(parsed, field)
