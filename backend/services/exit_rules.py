"""Shared, versioned V2 trailing rule for paper and historical replay."""
import math
from backend.services.costs import tick_size


def trail_v2(symbol, side, entry, initial_stop, stop, price, ema):
    risk = abs(entry - initial_stop)
    if not all(math.isfinite(x) for x in (entry, initial_stop, stop, price)) or risk <= 0:
        return stop
    activated = (price >= entry + risk or stop >= entry) if side == "long" else (price <= entry - risk or stop <= entry)
    if not activated:
        return stop
    if side == "long":
        candidate = max(stop, entry)
        if ema is not None and math.isfinite(ema):
            candidate = max(candidate, min(ema, price - risk * .25))
        rounded = math.floor(candidate / tick_size(symbol)) * tick_size(symbol)
        return max(stop, rounded)
    candidate = min(stop, entry)
    if ema is not None and math.isfinite(ema):
        candidate = min(candidate, max(ema, price + risk * .25))
    rounded = math.ceil(candidate / tick_size(symbol)) * tick_size(symbol)
    return min(stop, rounded)
