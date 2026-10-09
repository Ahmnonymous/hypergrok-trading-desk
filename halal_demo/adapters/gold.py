"""Gold is classified from contract fields, never from the letters XAUUSD."""

from __future__ import annotations

from halal_demo.adapters.mt5_constants import (
    CFD_CALC_MODES,
    FUTURES_CALC_MODES,
    SYMBOL_CALC_MODE_FOREX,
)

# Names that must use the gold gate. This is not an approval list.
GOLD_NAME_PREFIXES = ("XAU", "GOLD")


def is_gold_instrument(name: str, path: str | None = None) -> bool:
    base = name.upper().split(".")[0].replace("/", "")
    if base.startswith(GOLD_NAME_PREFIXES) or base in {"XAUUSD", "GOLD"}:
        return True
    if path and "metal" in path.lower():
        return True
    return False


def gold_contract_type(calc_mode: int | None) -> str:
    """Map a MetaTrader calculation mode to a gold contract label.

    MetaTrader symbol info cannot prove allocated, deliverable metal.
    `identified_deliverable_spot` is intentionally never returned here.
    """
    if calc_mode in CFD_CALC_MODES:
        return "cfd"
    if calc_mode in FUTURES_CALC_MODES:
        return "futures"
    if calc_mode == SYMBOL_CALC_MODE_FOREX:
        return "leveraged_forex"
    return "unidentified_gold_otc"
