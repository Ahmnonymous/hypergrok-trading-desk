"""Destination proof. Demo status comes from the adapter, never from an agent."""

from __future__ import annotations

from dataclasses import dataclass

from halal_demo.errors import DemoOnlyError

ALLOWED_ACCOUNT_TYPES = frozenset({"demo", "paper", "testnet"})
LOCAL_TRANSPORT = "local_simulator"
LOCAL_ENDPOINT = "local-simulator"
ADAPTER_SOURCE = "adapter_configuration"


@dataclass(frozen=True)
class DestinationProof:
    venue: str
    account_type: str
    transport: str
    network_orders_enabled: bool
    endpoint_label: str
    proof_source: str
    trade_mode_name: str
    detail: str


@dataclass(frozen=True)
class GuardDecision:
    status: str
    reasons: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def verify_destination(proof: DestinationProof) -> GuardDecision:
    reasons: list[str] = []
    if proof.proof_source != ADAPTER_SOURCE:
        reasons.append("demo_proof_not_from_adapter")
    if proof.transport != LOCAL_TRANSPORT:
        reasons.append("transport_is_not_local_simulator")
    if proof.network_orders_enabled is not False:
        reasons.append("network_orders_not_disabled")
    if proof.endpoint_label != LOCAL_ENDPOINT:
        reasons.append("endpoint_is_not_local_simulator")
    if proof.account_type not in ALLOWED_ACCOUNT_TYPES:
        reasons.append(f"account_type_rejected:{proof.account_type or 'missing'}")
    if proof.trade_mode_name in {"real", "live", "contest", "unknown", ""}:
        reasons.append(f"trade_mode_rejected:{proof.trade_mode_name or 'missing'}")
    if proof.account_type == "live" or proof.trade_mode_name in {"real", "live"}:
        reasons.append("live_account_rejected")
    if reasons:
        return GuardDecision("REJECT", tuple(dict.fromkeys(reasons)))
    return GuardDecision("PASS", ())


def refuse_network(action: str) -> None:
    raise DemoOnlyError(
        f"refusing {action}: this build has no live, demo-network, or testnet session"
    )
