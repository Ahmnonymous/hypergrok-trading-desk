"""Load OHLC fixtures. Live downloads are refused."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from halal_demo.clock import parse_utc
from halal_demo.decimals import parse_decimal


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Dataset:
    version: str
    source: str
    label: str
    as_of: datetime
    symbol: str
    bars: tuple[Bar, ...]


def load_dataset(csv_path: Path, meta_path: Path) -> Dataset:
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    required = ("dataset_version", "source", "label", "as_of", "symbol")
    missing = [key for key in required if not meta.get(key)]
    if missing:
        raise ValueError("dataset metadata missing " + ", ".join(missing))
    if meta["label"] not in {"synthetic", "offline_fixture"}:
        raise ValueError("refusing dataset that is not labeled synthetic or offline_fixture")
    bars: list[Bar] = []
    with Path(csv_path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"timestamp", "open", "high", "low", "close"} <= set(reader.fieldnames):
            raise ValueError("ohlc columns are incomplete")
        for row in reader:
            bar = Bar(
                timestamp=parse_utc(row["timestamp"], "timestamp"),
                open=parse_decimal(row["open"], "open"),
                high=parse_decimal(row["high"], "high"),
                low=parse_decimal(row["low"], "low"),
                close=parse_decimal(row["close"], "close"),
            )
            if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
                raise ValueError(f"corrupt ohlc at {bar.timestamp.isoformat()}")
            bars.append(bar)
    if len(bars) < 2:
        raise ValueError("dataset needs at least two bars")
    ordered = tuple(sorted(bars, key=lambda item: item.timestamp))
    if len({item.timestamp for item in ordered}) != len(ordered):
        raise ValueError("duplicate timestamps")
    return Dataset(meta["dataset_version"], meta["source"], meta["label"], parse_utc(meta["as_of"], "as_of"), meta["symbol"], ordered)
