"""Venue adapters. All of them are local simulators in this build."""

from halal_demo.adapters.binance_spot import SimulatedBinanceSpot
from halal_demo.adapters.mt5 import MT5Adapter, SimulatedMT5Terminal
from halal_demo.adapters.stock_paper import SimulatedAlpacaPaper

__all__ = [
    "MT5Adapter",
    "SimulatedMT5Terminal",
    "SimulatedAlpacaPaper",
    "SimulatedBinanceSpot",
]
