"""Long-only moving-average crossover on an offline dataset.

A signal at bar i uses closes up to i. The fill, if any, is the next bar's
open. A finished report never authorizes an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from halal_demo.decimals import parse_decimal
from halal_demo.research.loader import Dataset


@dataclass(frozen=True)
class ResearchParams:
    fast: int
    slow: int
    in_sample_fraction: Decimal
    spread: Decimal
    slippage: Decimal
    fee_per_fill: Decimal
    size: Decimal

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchParams":
        fast = data.get("fast")
        slow = data.get("slow")
        if isinstance(fast, bool) or not isinstance(fast, int) or isinstance(slow, bool) or not isinstance(slow, int):
            raise ValueError("fast and slow windows are required integers")
        if fast < 1 or slow <= fast:
            raise ValueError("slow window must be greater than fast window, and both at least 1")
        fraction = parse_decimal(data["in_sample_fraction"], "in_sample_fraction")
        if fraction <= 0 or fraction >= 1:
            raise ValueError("in_sample_fraction must be between 0 and 1")
        spread = parse_decimal(data["spread"], "spread")
        slippage = parse_decimal(data["slippage"], "slippage")
        fee = parse_decimal(data["fee_per_fill"], "fee_per_fill")
        size = parse_decimal(data["size"], "size")
        if min(spread, slippage, fee) < 0 or size <= 0:
            raise ValueError("costs cannot be negative and size must be positive")
        return cls(fast, slow, fraction, spread, slippage, fee, size)


@dataclass(frozen=True)
class TradeRecord:
    entry_index: int
    exit_index: int
    entry_price: Decimal
    exit_price: Decimal
    net: Decimal
    region: str


@dataclass(frozen=True)
class ResearchReport:
    dataset_version: str
    dataset_label: str
    dataset_source: str
    params: dict
    in_sample: dict
    out_of_sample: dict
    baseline_out_of_sample: dict
    trades: tuple[TradeRecord, ...]
    execution_authorized: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_authorized", False)

    def authorizes_execution(self) -> bool:
        return False


def signal_at(closes: list[Decimal], index: int, fast: int, slow: int) -> str | None:
    """Return 'up', 'down', or None using closes at indexes <= index."""
    if index < slow:
        return None
    prev_fast = _mean(closes, index - 1, fast)
    prev_slow = _mean(closes, index - 1, slow)
    now_fast = _mean(closes, index, fast)
    now_slow = _mean(closes, index, slow)
    if None in (prev_fast, prev_slow, now_fast, now_slow):
        return None
    assert prev_fast is not None and prev_slow is not None and now_fast is not None and now_slow is not None
    if prev_fast <= prev_slow and now_fast > now_slow:
        return "up"
    if prev_fast >= prev_slow and now_fast < now_slow:
        return "down"
    return None


def run_backtest(dataset: Dataset, params: ResearchParams) -> ResearchReport:
    if dataset.label not in {"synthetic", "offline_fixture"}:
        raise ValueError("backtest refused an unlabeled dataset")
    closes = [bar.close for bar in dataset.bars]
    split = int(len(dataset.bars) * params.in_sample_fraction)
    if split <= params.slow or split >= len(dataset.bars) - 1:
        raise ValueError("split does not leave a usable in-sample and out-of-sample window")
    trades: list[TradeRecord] = []
    entry_index = None
    entry_price = None
    for index in range(params.slow, len(closes) - 1):
        idea = signal_at(closes, index, params.fast, params.slow)
        fill_index = index + 1
        if idea == "up" and entry_index is None:
            entry_index = fill_index
            entry_price = _buy(dataset.bars[fill_index].open, params)
        elif idea == "down" and entry_index is not None and entry_price is not None:
            exit_price = _sell(dataset.bars[fill_index].open, params)
            net = (exit_price - entry_price) * params.size - params.fee_per_fill * 2
            trades.append(
                TradeRecord(entry_index, fill_index, entry_price, exit_price, net, _region(entry_index, split))
            )
            entry_index = None
            entry_price = None
    report_trades = tuple(trades)
    return ResearchReport(
        dataset_version=dataset.version,
        dataset_label=dataset.label,
        dataset_source=dataset.source,
        params={
            "fast": params.fast,
            "slow": params.slow,
            "in_sample_fraction": str(params.in_sample_fraction),
            "spread": str(params.spread),
            "slippage": str(params.slippage),
            "fee_per_fill": str(params.fee_per_fill),
            "size": str(params.size),
        },
        in_sample=_metrics([item for item in report_trades if item.region == "in_sample"]),
        out_of_sample=_metrics([item for item in report_trades if item.region == "out_of_sample"]),
        baseline_out_of_sample=_baseline(dataset, params, split),
        trades=report_trades,
        execution_authorized=False,
    )


def _mean(closes: list[Decimal], end: int, window: int) -> Decimal | None:
    if end < window - 1 or end >= len(closes):
        return None
    chunk = closes[end + 1 - window : end + 1]
    if len(chunk) != window:
        return None
    return sum(chunk, Decimal(0)) / Decimal(window)


def _buy(price: Decimal, params: ResearchParams) -> Decimal:
    return price + params.spread + params.slippage


def _sell(price: Decimal, params: ResearchParams) -> Decimal:
    return price - params.spread - params.slippage


def _region(entry_index: int, split: int) -> str:
    if entry_index < split:
        return "in_sample"
    return "out_of_sample"


def _metrics(trades: list[TradeRecord]) -> dict:
    nets = [item.net for item in trades]
    wins = [item for item in nets if item > 0]
    losses = [item for item in nets if item <= 0]
    equity = Decimal(0)
    peak = Decimal(0)
    drawdown = Decimal(0)
    for net in nets:
        equity += net
        if equity > peak:
            peak = equity
        drop = peak - equity
        if drop > drawdown:
            drawdown = drop
    return {
        "trade_count": len(trades),
        "win_rate": (Decimal(len(wins)) / Decimal(len(trades))) if trades else None,
        "avg_gain": (sum(wins, Decimal(0)) / Decimal(len(wins))) if wins else None,
        "avg_loss": (sum(losses, Decimal(0)) / Decimal(len(losses))) if losses else None,
        "net": sum(nets, Decimal(0)),
        "max_drawdown": drawdown,
    }


def _baseline(dataset: Dataset, params: ResearchParams, split: int) -> dict:
    entry = _buy(dataset.bars[split].open, params)
    exit_price = _sell(dataset.bars[-1].close, params)
    net = (exit_price - entry) * params.size - params.fee_per_fill * 2
    return {
        "description": "buy the first out-of-sample open and sell the last close, same costs",
        "net": net,
        "trade_count": 1,
    }
