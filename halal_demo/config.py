"""Load and check JSON configs. Missing limits are errors, not defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from halal_demo.clock import parse_utc
from halal_demo.decimals import parse_decimal
from halal_demo.errors import ConfigError

SECRET_MARKERS = ("api_key", "api_secret", "secret", "password", "private_key", "token")


def load_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError([f"cannot read {path}: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ConfigError([f"{path} must be a JSON object"])
    _reject_secrets(data)
    return data


def _reject_secrets(data: dict) -> None:
    found = []

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                folded = str(key).lower()
                if any(marker in folded for marker in SECRET_MARKERS):
                    if value not in (None, "", False):
                        found.append(prefix + str(key))
                walk(value, prefix + str(key) + ".")
        elif isinstance(node, list):
            for item in node:
                walk(item, prefix)

    walk(data, "")
    if found:
        raise ConfigError(["config contains secret values: " + ", ".join(found)])


def require_text(data: dict, field: str, errors: list[str]) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"missing:{field}")
        return ""
    return value.strip()


def require_percent(data: dict, field: str, errors: list[str]) -> Decimal | None:
    if field not in data:
        errors.append(f"missing:{field}")
        return None
    try:
        number = parse_decimal(data[field], field)
    except ValueError:
        errors.append(f"invalid:{field}")
        return None
    if number <= 0 or number > 100:
        errors.append(f"out_of_range:{field}")
        return None
    return number


def require_int(data: dict, field: str, errors: list[str]) -> int | None:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"missing_or_invalid:{field}")
        return None
    if value <= 0:
        errors.append(f"out_of_range:{field}")
        return None
    return value


def require_time(data: dict, field: str, errors: list[str]) -> datetime | None:
    value = data.get(field)
    if not isinstance(value, str):
        errors.append(f"missing:{field}")
        return None
    try:
        return parse_utc(value, field)
    except ValueError:
        errors.append(f"invalid:{field}")
        return None


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str
    allow_network_orders: bool
    transport: str
    allow_offline_test_policy: bool

    @classmethod
    def from_dict(cls, data: dict) -> "RuntimeConfig":
        errors: list[str] = []
        mode = require_text(data, "mode", errors)
        transport = require_text(data, "transport", errors)
        if data.get("allow_network_orders") is not False:
            errors.append("allow_network_orders must be false")
        if mode != "demo":
            errors.append("mode must be demo")
        if transport != "local_simulator":
            errors.append("transport must be local_simulator")
        flag = data.get("allow_offline_test_policy", False)
        if not isinstance(flag, bool):
            errors.append("allow_offline_test_policy must be a boolean")
            flag = False
        if errors:
            raise ConfigError(errors)
        return cls(mode, False, transport, flag)
