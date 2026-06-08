"""
V2 — Global Trading Sessions (Section 1)
========================================

Three rolling session profiles, 24/5, all times in US Eastern (ET).
The engine identifies which session is active for any given bar, whether we
are inside that session's "kill zone" (peak volatility window), and whether
we are in the London/New-York overlap.

Times follow the spec table:

    Session    Window (ET)          Kill Zone (ET)        Macro Anchor
    ASIA       08:00 PM – 04:00 AM  08:00 PM – 10:00 PM   prior NY range
    LONDON     04:00 AM – 12:00 PM  04:00 AM – 06:00 AM   Asia range
    NEW YORK   09:00 AM – 06:00 PM  09:30 AM – 11:30 AM   London range

Rules:
  • Volatility Pause: no setups in the FIRST 5 MINUTES of a kill zone.
  • Overlap (09:00–12:00 ET): London + NY both live → prioritise NY levels.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dtime


@dataclass(frozen=True)
class Session:
    name: str
    start: dtime
    end: dtime
    kill_start: dtime
    kill_end: dtime
    preceding: str        # session whose range anchors this one's macro zones
    max_rr: float         # 1.0 = truncate (Asia), 2.0 = allow expansion (LDN/NY)
    micro_preferred: bool # True → prefer MNQ micros to capture broader moves


ASIA = Session(
    name="ASIA",
    start=dtime(20, 0), end=dtime(4, 0),
    kill_start=dtime(20, 0), kill_end=dtime(22, 0),
    preceding="NEW_YORK", max_rr=1.0, micro_preferred=True,
)
LONDON = Session(
    name="LONDON",
    start=dtime(4, 0), end=dtime(12, 0),
    kill_start=dtime(4, 0), kill_end=dtime(6, 0),
    preceding="ASIA", max_rr=2.0, micro_preferred=False,
)
NEW_YORK = Session(
    name="NEW_YORK",
    start=dtime(9, 0), end=dtime(18, 0),
    kill_start=dtime(9, 30), kill_end=dtime(11, 30),
    preceding="LONDON", max_rr=2.0, micro_preferred=False,
)

# Priority order for the overlap rule: NY wins, then London, then Asia.
ALL_SESSIONS = [NEW_YORK, LONDON, ASIA]
BY_NAME = {s.name: s for s in ALL_SESSIONS}

# Volatility pause: skip the first N minutes of a kill zone.
KILL_ZONE_PAUSE_MIN = 5


def _minute_of_day(t) -> int:
    return t.hour * 60 + t.minute


def _in_window(m: int, start: dtime, end: dtime) -> bool:
    """True if minute-of-day m is inside [start, end), wrap-aware for Asia."""
    s, e = _minute_of_day(start), _minute_of_day(end)
    if s <= e:
        return s <= m < e
    return m >= s or m < e   # window crosses midnight


def active_session(ts) -> Session | None:
    """Return the highest-priority active session for an ET timestamp, or None."""
    m = _minute_of_day(ts)
    for s in ALL_SESSIONS:          # NY → LONDON → ASIA (overlap rule)
        if _in_window(m, s.start, s.end):
            return s
    return None


def in_kill_zone(ts, session: Session) -> bool:
    return _in_window(_minute_of_day(ts), session.kill_start, session.kill_end)


def in_volatility_pause(ts, session: Session) -> bool:
    """True during the first KILL_ZONE_PAUSE_MIN minutes of the kill zone."""
    m = _minute_of_day(ts)
    ks = _minute_of_day(session.kill_start)
    # kill zones never wrap midnight in this table, so a simple range is safe
    return ks <= m < ks + KILL_ZONE_PAUSE_MIN


def in_overlap(ts) -> bool:
    """London + NY both live (09:00–12:00 ET)."""
    m = _minute_of_day(ts)
    return _in_window(m, NEW_YORK.start, LONDON.end)


def minutes_since_session_open(ts, session: Session) -> int:
    """How many minutes since this session's start (wrap-aware)."""
    m = _minute_of_day(ts)
    s = _minute_of_day(session.start)
    diff = m - s
    if diff < 0:
        diff += 24 * 60
    return diff
