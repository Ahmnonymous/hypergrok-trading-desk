"""Verification result shared by venue adapters."""

from __future__ import annotations

from dataclasses import dataclass

from halal_demo.demo_guard import DestinationProof
from halal_demo.risk import CostInputs
from halal_demo.shariah import InstrumentFacts


@dataclass(frozen=True)
class Verification:
    ok: bool
    reasons: tuple[str, ...]
    facts: InstrumentFacts | None
    costs: CostInputs | None
    proof: DestinationProof | None
    trading_hours_open: bool | None
