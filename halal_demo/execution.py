"""Single writer for simulated orders. One attempt, then reconcile."""

from __future__ import annotations

from dataclasses import dataclass

from halal_demo.adapters.book import PreparedOrder
from halal_demo.errors import DemoOnlyError
from halal_demo.journal import Journal
from halal_demo.killswitch import KillSwitch


@dataclass(frozen=True)
class SubmitOutcome:
    status: str
    reason: str | None
    created: bool


class ExecutionService:
    def __init__(self, journal: Journal, kill_switch: KillSwitch):
        self.journal = journal
        self.kill_switch = kill_switch

    def submit(self, adapter, order: PreparedOrder) -> SubmitOutcome:
        if order.network_send:
            return SubmitOutcome("blocked", "network_send_refused", False)
        if self.kill_switch.active:
            self._apply_kill_switch(adapter)
            return SubmitOutcome("blocked", "kill_switch", False)
        if self.journal.attempts_for(order.proposal_id) >= 1:
            if self._awaiting_reconcile(order.proposal_id):
                return SubmitOutcome("blocked", "reconcile_before_retry", False)
            return SubmitOutcome("blocked", "one_attempt_already_used", False)
        self.journal.append(
            {
                "event": "submit_attempt",
                "proposal_id": order.proposal_id,
                "idempotency_id": order.idempotency_id,
                "venue": order.venue,
                "instrument": order.instrument,
                "network_send": False,
            }
        )
        try:
            result = adapter.simulated_submit(order)
        except DemoOnlyError as exc:
            self.journal.append(
                {
                    "event": "submit_result",
                    "proposal_id": order.proposal_id,
                    "idempotency_id": order.idempotency_id,
                    "status": "rejected",
                    "reason": str(exc),
                    "network_send": False,
                }
            )
            return SubmitOutcome("rejected", "demo_only", False)
        except Exception as exc:  # noqa: BLE001 - uncertain transport must not be retried
            self.journal.append(
                {
                    "event": "submit_result",
                    "proposal_id": order.proposal_id,
                    "idempotency_id": order.idempotency_id,
                    "status": "uncertain",
                    "reason": type(exc).__name__,
                    "network_send": False,
                }
            )
            return SubmitOutcome("uncertain", "submit_raised", False)
        status = result.get("status", "uncertain")
        self.journal.append(
            {
                "event": "submit_result",
                "proposal_id": order.proposal_id,
                "idempotency_id": order.idempotency_id,
                "status": status,
                "created": bool(result.get("created")),
                "network_send": False,
            }
        )
        if status == "uncertain":
            return SubmitOutcome("uncertain", "broker_acknowledgement_unknown", bool(result.get("created")))
        if status in {"filled", "new", "open"} and result.get("created"):
            return SubmitOutcome("accepted", None, True)
        if status == "unavailable":
            return SubmitOutcome("unavailable", "api_unavailable", False)
        return SubmitOutcome("rejected", status, False)

    def reconcile(self, adapter, order: PreparedOrder) -> tuple[bool, str]:
        found = adapter.read_order(order.idempotency_id)
        if found is None:
            self.journal.append(
                {
                    "event": "reconcile",
                    "proposal_id": order.proposal_id,
                    "idempotency_id": order.idempotency_id,
                    "status": "absent",
                    "network_send": False,
                }
            )
            return False, "broker_state_absent"
        match = (
            found.instrument.upper() == order.instrument.upper()
            and found.side == order.side
            and found.price == order.price
            and found.quantity == order.quantity
            and found.stop_loss == order.stop_loss
            and found.status in {"filled", "new", "open", "cancelled"}
        )
        self.journal.append(
            {
                "event": "reconcile",
                "proposal_id": order.proposal_id,
                "idempotency_id": order.idempotency_id,
                "status": found.status,
                "match": match,
                "network_send": False,
            }
        )
        if not match:
            return False, "broker_state_mismatch"
        return True, found.status

    def _awaiting_reconcile(self, proposal_id: str) -> bool:
        rows = [row for row in self.journal.read() if row.get("proposal_id") == proposal_id]
        attempted = any(row.get("event") == "submit_attempt" for row in rows)
        reconciled = any(row.get("event") == "reconcile" for row in rows)
        return attempted and not reconciled

    def _apply_kill_switch(self, adapter) -> None:
        state = self.kill_switch.state
        cancelled: list[str] = []
        if state.order_policy == "cancel_unfilled_in_simulator":
            cancelled = adapter.cancel_unfilled()
        self.journal.append(
            {
                "event": "kill_switch",
                "actor": state.actor,
                "order_policy": state.order_policy,
                "position_policy": state.position_policy,
                "reason": state.reason,
                "cancelled_order_ids": cancelled,
                "positions": "held",
                "network_send": False,
            }
        )
