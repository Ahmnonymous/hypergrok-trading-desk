"""Execution states. A failed step stops the chain and records why."""

from __future__ import annotations

from dataclasses import dataclass, field

STAGES = (
    "PROPOSED",
    "INSTRUMENT_VERIFIED",
    "SHARIAH_PASSED",
    "RISK_PASSED",
    "DEMO_ACCOUNT_VERIFIED",
    "ORDER_VALIDATED",
    "ORDER_SUBMITTED",
    "BROKER_STATE_RECONCILED",
    "TRADE_RECORDED",
)


@dataclass
class StageRecord:
    stage: str
    ok: bool
    reason: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    proposal_id: str | None
    idempotency_id: str | None
    final_status: str
    execution_status: str
    stages: list[StageRecord]
    block_reason: str | None
    order_count: int
    network_send: bool = False

    def stage_names(self) -> list[str]:
        return [item.stage for item in self.stages if item.ok]
