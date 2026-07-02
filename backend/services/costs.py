"""
Trading friction model — commission + slippage.

Shared by the live paper broker, the execution layer, and both backtesters so
paper P&L and backtest P&L stop flattering themselves. Defaults follow the
project review: ~$1.50/side/contract commission and 1 tick of adverse
slippage on market-order fills (entries and stop exits). Limit-style target
fills are assumed to fill at price.
"""
from __future__ import annotations

TICK_SIZES = {
    "MES": 0.25,
    "MNQ": 0.25,
    "NQ": 0.25,
    "ES": 0.25,
    "MGC": 0.10,
    "MYM": 1.0,
    "M2K": 0.10,
}


def tick_size(symbol: str) -> float:
    return TICK_SIZES.get(symbol.upper(), 0.25)


def slippage_points(symbol: str, ticks: int) -> float:
    """Adverse price movement (in points) applied to a market-order fill."""
    return tick_size(symbol) * max(0, ticks)


def slip_entry(symbol: str, side: str, price: float, ticks: int) -> float:
    """Entry market order fills 1 tick against you: longs pay up, shorts sell down."""
    slip = slippage_points(symbol, ticks)
    return price + slip if side == "long" else price - slip


def slip_stop_exit(symbol: str, side: str, stop: float, ticks: int) -> float:
    """Stop-loss becomes a market order when touched — fills through the level."""
    slip = slippage_points(symbol, ticks)
    return stop - slip if side == "long" else stop + slip


def round_trip_commission(qty: int, per_side: float) -> float:
    return qty * per_side * 2.0
