"""Health checks. An unknown component is unhealthy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class HealthReport:
    components: tuple[ComponentHealth, ...]

    @property
    def ok(self) -> bool:
        return bool(self.components) and all(item.ok for item in self.components)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "components": [
                {"name": item.name, "ok": item.ok, "detail": item.detail}
                for item in self.components
            ],
        }
