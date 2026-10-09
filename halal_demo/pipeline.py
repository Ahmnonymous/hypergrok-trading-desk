"""Run one proposal through the gates. A rejection is not rewritten into a new idea."""

from __future__ import annotations

from dataclasses import dataclass, field

from halal_demo.config import RuntimeConfig
from halal_demo.demo_guard import verify_destination
from halal_demo.execution import ExecutionService
from halal_demo.health import ComponentHealth, HealthReport
from halal_demo.journal import Journal
from halal_demo.killswitch import KillSwitch
from halal_demo.risk import AccountState, OpenExposure, PositionBook, RiskLimits, evaluate_risk, refuse_agent_override
from halal_demo.schema import parse_proposal
from halal_demo.shariah import ShariahPolicy, evaluate
from halal_demo.state import STAGES, PipelineResult, StageRecord


@dataclass
class Desk:
    clock: object
    policy: ShariahPolicy
    limits: RiskLimits
    runtime: RuntimeConfig
    adapters: dict
    journal: Journal
    book: PositionBook = field(default_factory=PositionBook)
    kill_switch: KillSwitch = field(default_factory=KillSwitch)
    health_overrides: dict | None = None

    def execution(self) -> ExecutionService:
        return ExecutionService(self.journal, self.kill_switch)

    def health(self) -> HealthReport:
        components = []
        for name, adapter in self.adapters.items():
            if self.health_overrides and name in self.health_overrides:
                components.append(self.health_overrides[name])
            else:
                components.append(adapter.health())
        components.append(
            ComponentHealth(
                "kill_switch",
                not self.kill_switch.active,
                "clear" if not self.kill_switch.active else "active",
            )
        )
        components.append(ComponentHealth("runtime", self.runtime.allow_network_orders is False, self.runtime.mode))
        return HealthReport(tuple(components))


def activate_kill_switch(desk: Desk, *, actor: str, order_policy: str, position_policy: str, reason: str) -> None:
    """Apply an explicit outstanding-order and position policy, then block new sends."""
    desk.kill_switch.activate(
        actor=actor,
        order_policy=order_policy,
        position_policy=position_policy,
        reason=reason,
    )
    service = desk.execution()
    for adapter in desk.adapters.values():
        service._apply_kill_switch(adapter)


def run_proposal(raw: object, desk: Desk) -> PipelineResult:
    now = desk.clock.now()
    parsed = parse_proposal(raw, now)
    stages: list[StageRecord] = []
    proposal_id = parsed.proposal_id
    idempotency_id = parsed.idempotency_id
    known_proposals, known_idem = desk.journal.known_ids()
    if proposal_id and proposal_id in known_proposals or idempotency_id and idempotency_id in known_idem:
        _blocked(desk, proposal_id, idempotency_id, "duplicate_proposal", stages)
        return _result(proposal_id, idempotency_id, stages, "duplicate_proposal", 0)

    if not parsed.ok or parsed.proposal is None:
        if proposal_id:
            desk.journal.append(
                {
                    "event": "proposal_received",
                    "proposal_id": proposal_id,
                    "idempotency_id": idempotency_id,
                    "status": "blocked",
                    "network_send": False,
                }
            )
        reason = ",".join(parsed.reasons) if parsed.reasons else "malformed"
        _blocked(desk, proposal_id, idempotency_id, reason, stages)
        return _result(proposal_id, idempotency_id, stages, reason, 0)

    proposal = parsed.proposal
    desk.journal.append(
        {
            "event": "proposal_received",
            "proposal_id": proposal.proposal_id,
            "idempotency_id": proposal.idempotency_id,
            "instrument": proposal.instrument,
            "venue": proposal.venue,
            "claimed_shariah_result": proposal.claimed_shariah_result,
            "claimed_risk_result": proposal.claimed_risk_result,
            "network_send": False,
        }
    )
    stages.append(StageRecord("PROPOSED", True))
    if desk.kill_switch.active:
        return _stop(desk, proposal, stages, "kill_switch", "PROPOSED")

    adapter = desk.adapters.get(proposal.venue)
    if adapter is None:
        return _stop(desk, proposal, stages, "api_unavailable", "PROPOSED")
    health = adapter.health()
    if desk.health_overrides and proposal.venue in desk.health_overrides:
        health = desk.health_overrides[proposal.venue]
    if not health.ok:
        return _stop(desk, proposal, stages, "unhealthy_services", "PROPOSED")

    verification = adapter.verify(proposal)
    if not verification.ok or verification.facts is None or verification.costs is None or verification.proof is None:
        reason = ",".join(verification.reasons) if verification.reasons else "instrument_not_verified"
        return _stop(desk, proposal, stages, reason, "PROPOSED")
    stages.append(StageRecord("INSTRUMENT_VERIFIED", True, detail={"contract_type": verification.facts.contract_type}))

    decision = evaluate(
        verification.facts,
        desk.policy,
        now,
        allow_offline_test_policy=desk.runtime.allow_offline_test_policy,
    )
    desk.journal.append(
        {
            "event": "shariah",
            "proposal_id": proposal.proposal_id,
            "status": decision.status,
            "rule_version": decision.rule_version,
            "reasons": list(decision.reasons),
            "reviewer": decision.reviewer,
            "network_send": False,
        }
    )
    if not decision.passed:
        return _stop(desk, proposal, stages, f"shariah:{decision.status}:{','.join(decision.reasons)}", "INSTRUMENT_VERIFIED")
    stages.append(StageRecord("SHARIAH_PASSED", True, detail={"rule_version": decision.rule_version}))

    limits, override_note = refuse_agent_override(
        desk.limits,
        {"risk_result": proposal.claimed_risk_result} if proposal.claimed_risk_result else None,
    )
    account = adapter.account_state()
    if not isinstance(account, AccountState):
        return _stop(desk, proposal, stages, "missing:account", "SHARIAH_PASSED")
    age = (now - verification.facts.quoted_at).total_seconds() if verification.facts.quoted_at else None
    stale = age is None or age > limits.max_price_age_seconds
    risk = evaluate_risk(
        proposal,
        verification.costs,
        limits,
        account,
        desk.book,
        now,
        price_is_stale=stale,
        services_healthy=True,
    )
    desk.journal.append(
        {
            "event": "risk",
            "proposal_id": proposal.proposal_id,
            "status": risk.status,
            "rule_version": risk.rule_version,
            "reasons": list(risk.reasons),
            "worst_case_loss_account": str(risk.worst_case_loss_account) if risk.worst_case_loss_account is not None else None,
            "agent_override": override_note,
            "network_send": False,
        }
    )
    if not risk.passed or risk.worst_case_loss_account is None:
        return _stop(desk, proposal, stages, f"risk:{','.join(risk.reasons)}", "SHARIAH_PASSED")
    stages.append(StageRecord("RISK_PASSED", True, detail={"rule_version": risk.rule_version}))

    guard = verify_destination(verification.proof)
    if not guard.passed:
        return _stop(desk, proposal, stages, "demo_guard:" + ",".join(guard.reasons), "RISK_PASSED")
    stages.append(StageRecord("DEMO_ACCOUNT_VERIFIED", True))

    prepared, prepare_reasons = adapter.prepare(proposal, verification.costs)
    if prepared is None:
        return _stop(desk, proposal, stages, ",".join(prepare_reasons), "DEMO_ACCOUNT_VERIFIED")
    if prepared.network_send:
        return _stop(desk, proposal, stages, "network_send_refused", "DEMO_ACCOUNT_VERIFIED")
    stages.append(StageRecord("ORDER_VALIDATED", True))

    if desk.kill_switch.active:
        return _stop(desk, proposal, stages, "kill_switch", "ORDER_VALIDATED")
    outcome = desk.execution().submit(adapter, prepared)
    if outcome.status == "uncertain":
        _blocked(desk, proposal.proposal_id, proposal.idempotency_id, "uncertain_submission", stages)
        stages.append(StageRecord("ORDER_SUBMITTED", False, "uncertain_submission"))
        return _result(proposal.proposal_id, proposal.idempotency_id, stages, "uncertain_submission", _order_count(adapter))
    if outcome.status != "accepted":
        return _stop(desk, proposal, stages, outcome.reason or outcome.status, "ORDER_VALIDATED")
    stages.append(StageRecord("ORDER_SUBMITTED", True, detail={"network_send": False}))

    matched, reconcile_reason = desk.execution().reconcile(adapter, prepared)
    if not matched:
        return _stop(desk, proposal, stages, reconcile_reason, "ORDER_SUBMITTED")
    stages.append(StageRecord("BROKER_STATE_RECONCILED", True, detail={"broker_status": reconcile_reason}))

    desk.book.add(
        OpenExposure(
            proposal.proposal_id,
            proposal.instrument,
            proposal.venue,
            risk.worst_case_loss_account,
            proposal.size,
        )
    )
    desk.journal.append(
        {
            "event": "recorded",
            "proposal_id": proposal.proposal_id,
            "idempotency_id": proposal.idempotency_id,
            "execution_status": "TRADE_RECORDED",
            "shariah_result": decision.status,
            "shariah_rule_version": decision.rule_version,
            "risk_result": risk.status,
            "risk_rule_version": risk.rule_version,
            "worst_case_loss_account": str(risk.worst_case_loss_account),
            "network_send": False,
            "destination": "local_simulator",
        }
    )
    stages.append(StageRecord("TRADE_RECORDED", True))
    return PipelineResult(
        proposal.proposal_id,
        proposal.idempotency_id,
        "TRADE_RECORDED",
        "TRADE_RECORDED",
        stages,
        None,
        _order_count(adapter),
        False,
    )


def _stop(desk: Desk, proposal, stages: list[StageRecord], reason: str, last_ok: str) -> PipelineResult:
    failed = _next_stage(last_ok)
    stages.append(StageRecord(failed, False, reason))
    _blocked(desk, proposal.proposal_id, proposal.idempotency_id, reason, stages)
    adapter = desk.adapters.get(proposal.venue)
    count = _order_count(adapter) if adapter is not None else 0
    return _result(proposal.proposal_id, proposal.idempotency_id, stages, reason, count)


def _next_stage(last_ok: str) -> str:
    index = STAGES.index(last_ok)
    if index + 1 < len(STAGES):
        return STAGES[index + 1]
    return "BLOCKED"


def _blocked(desk: Desk, proposal_id, idempotency_id, reason: str, stages: list[StageRecord]) -> None:
    desk.journal.append(
        {
            "event": "blocked",
            "proposal_id": proposal_id,
            "idempotency_id": idempotency_id,
            "reason": reason,
            "stages": [item.stage for item in stages],
            "network_send": False,
        }
    )


def _result(proposal_id, idempotency_id, stages, reason, order_count) -> PipelineResult:
    return PipelineResult(proposal_id, idempotency_id, "BLOCKED", "BLOCKED", stages, reason, order_count, False)


def _order_count(adapter) -> int:
    reader = getattr(adapter, "read_order", None)
    book = getattr(adapter, "book", None)
    if book is None and hasattr(adapter, "terminal"):
        book = adapter.terminal.book
    if book is None:
        return 0
    return len(book.orders)
