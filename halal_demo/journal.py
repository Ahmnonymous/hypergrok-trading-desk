"""Append-only audit journal. Secret-looking fields are redacted before write."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECRET_KEY_PARTS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "token",
    "private_key",
    "authorization",
    "credential",
)
SECRET_VALUE_RE = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|xox[baprs]-)",
    re.IGNORECASE,
)
REDACTED = "[redacted]"


def _key_is_secret(key: str) -> bool:
    folded = key.lower().replace("-", "_")
    return any(part in folded for part in SECRET_KEY_PARTS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if _key_is_secret(str(key)):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and SECRET_VALUE_RE.search(value):
        return REDACTED
    return value


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self.path.is_file():
            raise ValueError("journal path is not a file")
        self.path.touch(exist_ok=True)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        record = redact(dict(event))
        record.setdefault("journal_time", datetime.now(timezone.utc).isoformat())
        record["network_orders_allowed"] = False
        line = json.dumps(record, sort_keys=True, default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def read(self) -> list[dict[str, Any]]:
        rows = []
        text = self.path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
        return rows

    def attempts_for(self, proposal_id: str) -> int:
        count = 0
        for row in self.read():
            if row.get("event") == "submit_attempt" and row.get("proposal_id") == proposal_id:
                count += 1
        return count

    def known_ids(self) -> tuple[set[str], set[str]]:
        proposals: set[str] = set()
        idempotency: set[str] = set()
        for row in self.read():
            if row.get("event") == "proposal_received":
                if row.get("proposal_id"):
                    proposals.add(row["proposal_id"])
                if row.get("idempotency_id"):
                    idempotency.add(row["idempotency_id"])
        return proposals, idempotency
