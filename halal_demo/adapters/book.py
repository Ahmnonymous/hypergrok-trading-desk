"""Shared order record for local simulators. Nothing here opens a socket."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class PreparedOrder:
    proposal_id: str
    idempotency_id: str
    venue: str
    instrument: str
    side: str
    order_type: str
    price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    quantity: Decimal
    market_data_label: str
    network_send: bool = False


@dataclass
class BrokerOrder:
    idempotency_id: str
    proposal_id: str
    instrument: str
    side: str
    price: Decimal
    quantity: Decimal
    stop_loss: Decimal
    status: str
    venue: str


@dataclass
class SimulatedBook:
    orders: dict[str, BrokerOrder] = field(default_factory=dict)
    uncertain: set[str] = field(default_factory=set)
    mode: str = "fill"
    network_calls: int = 0

    def place(self, order: PreparedOrder) -> dict:
        if order.network_send:
            raise RuntimeError("simulator refused a network send flag")
        if order.idempotency_id in self.orders:
            return {"status": "duplicate", "created": False, "order": self.orders[order.idempotency_id]}
        if self.mode == "unavailable":
            return {"status": "unavailable", "created": False, "order": None}
        status = "unknown" if self.mode == "uncertain" else "filled"
        stored = BrokerOrder(
            order.idempotency_id,
            order.proposal_id,
            order.instrument,
            order.side,
            order.price,
            order.quantity,
            order.stop_loss,
            status,
            order.venue,
        )
        self.orders[order.idempotency_id] = stored
        if self.mode == "uncertain":
            self.uncertain.add(order.idempotency_id)
            self.mode = "fill"
            return {"status": "uncertain", "created": True, "order": stored}
        return {"status": "filled", "created": True, "order": stored}

    def read(self, idempotency_id: str) -> BrokerOrder | None:
        order = self.orders.get(idempotency_id)
        if order and idempotency_id in self.uncertain:
            order.status = "filled"
            self.uncertain.discard(idempotency_id)
        return order

    def cancel_unfilled(self) -> list[str]:
        cancelled = []
        for idem, order in self.orders.items():
            if order.status in {"unknown", "new", "open"}:
                order.status = "cancelled"
                cancelled.append(idem)
                self.uncertain.discard(idem)
        return cancelled

    def open_order_count(self) -> int:
        return sum(1 for order in self.orders.values() if order.status in {"unknown", "new", "open", "filled"})
