"""Emergency kill switch.

Outstanding orders and positions follow an explicit policy. This build can
hold them or cancel unfilled simulator orders. It does not invent a closing
order for an open position, because that would be another send.
"""

from __future__ import annotations

from dataclasses import dataclass

ORDER_POLICIES = frozenset({"hold", "cancel_unfilled_in_simulator"})
POSITION_POLICIES = frozenset({"hold"})
ALLOWED_ACTORS = frozenset({"user", "operator"})


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    actor: str | None
    order_policy: str | None
    position_policy: str | None
    reason: str | None


class KillSwitch:
    def __init__(self) -> None:
        self.state = KillSwitchState(False, None, None, None, None)

    def activate(
        self,
        *,
        actor: str,
        order_policy: str,
        position_policy: str,
        reason: str,
    ) -> KillSwitchState:
        if actor not in ALLOWED_ACTORS:
            raise PermissionError("only user or operator can activate the kill switch")
        if order_policy not in ORDER_POLICIES:
            raise ValueError("unknown outstanding-order policy")
        if position_policy not in POSITION_POLICIES:
            raise ValueError("unknown outstanding-position policy")
        if not reason.strip():
            raise ValueError("kill switch reason is required")
        self.state = KillSwitchState(True, actor, order_policy, position_policy, reason.strip())
        return self.state

    @property
    def active(self) -> bool:
        return self.state.active
