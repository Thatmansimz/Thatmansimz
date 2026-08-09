"""
THE CLOCK. One source of truth for time in this system.

Before this module there were three clocks running at once and nothing said so:

  • log lines      — the host's local time (America/Phoenix on the trading Mac)
  • trade_date,
    sessions,
    kill zones,
    campaign days   — America/New_York, via datetime.now(ET)
  • entry_time,
    exit_time,
    triggered_at,
    created_at      — naive UTC, via the (now deprecated) datetime.utcnow()

A trade and the log line that describes it therefore displayed timestamps SEVEN
HOURS apart, and for any trade entered between 8 PM and midnight ET its
trade_date (ET) and its entry_time (UTC) disagreed about the calendar DAY. In a
project whose entire deliverable is an auditable record, nobody could reconcile
the log, the database and the dashboard without a conversion table.

The rule now:

  STORE in UTC (naive, unchanged on disk — existing rows stay valid).
  DECIDE in ET (sessions, day keys, limits — the exchange's clock).
  DISPLAY in ET (so what a human reads matches the record's own day boundary).

Storage stays naive UTC deliberately. Changing it would silently reinterpret
every row already written and put a discontinuity in the middle of a live
60-day campaign. The bug was never the storage — it was that the storage was
undeclared and the display was wrong.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytz

# The exchange clock. Every trading decision is keyed to this.
ET = pytz.timezone("America/New_York")

# Uptime is cycles completed / cycles a healthy engine could have completed, so
# it is only as correct as the assumed cadence.
#
# The scheduler sleeps 60s and THEN does work (a yfinance fetch), so one "cycle"
# is 60s + work, not 60s. Measured on the live engine the median gap is ~120s,
# capping a perfect day near 720 cycles — against a hardcoded 1440 a
# continuously-running engine renders as ~50% uptime. That is the same class of
# error as dividing today by a full day, just in the other direction.
#
# Deliberately NOT self-calibrated from observed cycles: inferring the cadence
# from the data would make the denominator track the numerator and uptime would
# always read 100%, which destroys the only signal that detects downtime. The
# cadence is therefore a stated assumption — override it via
# SCHEDULER_CYCLE_SECONDS and read cycle_seconds_assumed in the payload to see
# which value produced a given figure.
DEFAULT_CYCLE_SECONDS = 60
MINUTES_PER_DAY = 1440


def configured_cycle_seconds() -> int:
    """
    The assumed seconds-per-cycle, from settings when available.

    Imported lazily: backend.clock must stay dependency-free so the models can
    import it without a cycle back through config.
    """
    try:
        from backend.config import settings
        value = int(getattr(settings, "SCHEDULER_CYCLE_SECONDS", 0) or 0)
        return value if value > 0 else DEFAULT_CYCLE_SECONDS
    except Exception:
        return DEFAULT_CYCLE_SECONDS


# ── Storage ───────────────────────────────────────────────────────────────────

def utc_now() -> datetime:
    """
    Naive UTC, for DB columns.

    Byte-identical to the datetime.utcnow() this replaces, so no stored value
    changes meaning — but explicit, and not deprecated under Python 3.12+.
    (This project runs 3.14, where utcnow() emits DeprecationWarning.)
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Decisions ─────────────────────────────────────────────────────────────────

def et_now() -> datetime:
    """Timezone-aware 'now' on the exchange clock."""
    return datetime.now(ET)


def trading_day() -> date:
    """
    The trading date in EXCHANGE time, not the host's local time.

    Every gate in this system (sessions, kill zones, market hours) runs on ET.
    If the record were keyed on the host's local date instead, then on any
    non-ET machine the recorded day would flip mid-session — silently resetting
    the daily loss limit partway through the Asia window and shifting the
    equity curve one row off the trade log.
    """
    return et_now().date()


# ── Display ───────────────────────────────────────────────────────────────────

def utc_to_et(value: datetime | None) -> datetime | None:
    """
    Interpret a naive-UTC value from the database on the exchange clock.

    Naive input is assumed UTC because that is what utc_now() writes. An
    already-aware value is converted, not reinterpreted.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ET)


def et_iso(value: datetime | None) -> str | None:
    """A stored naive-UTC timestamp, rendered as an ET ISO-8601 string."""
    converted = utc_to_et(value)
    return converted.isoformat() if converted else None


# ── Uptime ────────────────────────────────────────────────────────────────────

def expected_cycles(on: date, cycle_seconds: int | None = None) -> int:
    """
    How many cycles a perfectly healthy engine would have completed on `on`.

    For a past day that is the whole day. For TODAY it is only the part of the
    day that has actually happened — otherwise a healthy engine reads 3% at
    00:43 ET and climbs all day, which looks exactly like an outage. Fixing
    that for one code path and not the other is why /api/forward-test/status
    used to report today's uptime as 100% and 3% in the same response.
    """
    cycle_seconds = cycle_seconds or configured_cycle_seconds()
    per_minute = 60.0 / max(1, cycle_seconds)
    today = trading_day()
    if on < today:
        return max(1, int(MINUTES_PER_DAY * per_minute))
    if on > today:
        # A date in the future has no elapsed time to measure against.
        return 1
    now = et_now()
    minutes_elapsed = max(1, now.hour * 60 + now.minute)
    return max(1, int(minutes_elapsed * per_minute))


def uptime_pct(cycles: int | None, on: date,
               cycle_seconds: int | None = None) -> float:
    """Cycles completed as a percentage of cycles that were possible."""
    return round(min(100.0, (cycles or 0) / expected_cycles(on, cycle_seconds) * 100.0), 1)
