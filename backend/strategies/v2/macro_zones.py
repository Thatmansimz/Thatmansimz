"""
V2 — Multi-Session Macro Structure (Section 2)
==============================================

Builds support / resistance zones from the PRECEDING session's footprint:

  • Macro Resistance Zone : highest wick → highest body of the preceding session.
  • Macro Support Zone    : lowest wick  → lowest body  of the preceding session.

These zones feed the two playbooks (mean reversion off the edge, or
break-and-retest through it).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.strategies.v2 import sessions as S


@dataclass
class Zone:
    low: float   # inner edge
    high: float  # outer edge

    def mid(self) -> float:
        return (self.low + self.high) / 2.0

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass
class MacroZones:
    resistance: Zone | None
    support: Zone | None
    source_session: str


def label_session_instances(et_index: pd.DatetimeIndex) -> list[tuple[str, int]]:
    """
    Tag every bar with (session_name, instance_id). instance_id increments each
    time we enter a new occurrence of a session, so contiguous bars of one
    session share an id. Bars outside all sessions get ("NONE", id).
    """
    labels: list[tuple[str, int]] = []
    last_name = None
    instance = -1
    for ts in et_index:
        sess = S.active_session(ts)
        name = sess.name if sess else "NONE"
        if name != last_name:
            instance += 1
            last_name = name
        labels.append((name, instance))
    return labels


def build_macro_zones(
    df: pd.DataFrame,
    et_index: pd.DatetimeIndex,
    labels: list[tuple[str, int]],
    current_session: S.Session,
    current_instance: int,
) -> MacroZones:
    """
    Find the most recent COMPLETED instance of the preceding session that ended
    before the current instance began, and draw zones from its candles.
    """
    preceding_name = current_session.preceding

    # gather candidate instance ids for the preceding session, before current
    candidate_ids = sorted(
        {inst for (name, inst) in labels
         if name == preceding_name and inst < current_instance},
        reverse=True,
    )
    if not candidate_ids:
        return MacroZones(resistance=None, support=None, source_session=preceding_name)

    target_id = candidate_ids[0]
    idxs = [i for i, (name, inst) in enumerate(labels)
            if name == preceding_name and inst == target_id]
    if not idxs:
        return MacroZones(resistance=None, support=None, source_session=preceding_name)

    seg = df.iloc[idxs]
    highest_wick = float(seg["high"].max())
    lowest_wick = float(seg["low"].min())
    # body extremes (top/bottom of candle bodies)
    body_top = float(pd.concat([seg["open"], seg["close"]], axis=1).max(axis=1).max())
    body_bottom = float(pd.concat([seg["open"], seg["close"]], axis=1).min(axis=1).min())

    resistance = Zone(low=body_top, high=highest_wick)
    support = Zone(low=lowest_wick, high=body_bottom)
    return MacroZones(resistance=resistance, support=support, source_session=preceding_name)
