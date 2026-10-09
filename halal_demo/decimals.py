"""Exact decimals. Floats are refused so money is never silently approximated."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field} must be a string or int, not {type(value).__name__}")
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field} is not a decimal") from exc
    elif isinstance(value, Decimal):
        number = value
    else:
        raise ValueError(f"{field} must be a string or int, not {type(value).__name__}")
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def require_positive(value: Decimal, field: str) -> Decimal:
    if value <= 0:
        raise ValueError(f"{field} must be > 0")
    return value
