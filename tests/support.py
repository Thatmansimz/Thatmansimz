"""
Shared test scaffolding.

Deliberately stdlib-only (unittest, no pytest). A regression suite for a live
trading engine must be runnable on the trading machine itself with
`python3 -m unittest`, without installing anything into the environment that
holds the campaign.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from datetime import date, datetime
from unittest import mock

import pytz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.trade import Base, DailyStats, EquitySnapshot, Trade
from backend.models.account import Account

ET = pytz.timezone("America/New_York")


def make_session():
    """A fresh in-memory database with the real schema."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def seed_account(db, balance: float = 50000.0):
    db.add(Account(broker="paper", balance=balance, equity=balance))
    db.commit()


@contextmanager
def frozen_et(when: datetime):
    """
    Pin the exchange clock.

    `trading_day` is re-exported through several modules, and each `from ... import
    trading_day` created an independent name bound to the same function. Patching
    only backend.clock would leave forward_test and main on the real clock, so
    every alias is patched together — the aliasing itself is what let three
    different clocks coexist unnoticed.
    """
    if when.tzinfo is None:
        when = ET.localize(when)
    day = when.date()

    targets = [
        ("backend.clock.et_now", lambda: when),
        ("backend.clock.trading_day", lambda: day),
    ]
    optional = [
        "backend.services.execution.trading_day",
        "backend.services.forward_test.trading_day",
        "backend.main.trading_day",
    ]

    patches = [mock.patch(t, new=fn) for t, fn in targets]
    for name in optional:
        try:
            patches.append(mock.patch(name, new=lambda d=day: d))
        except (AttributeError, ModuleNotFoundError):
            pass

    for p in patches:
        p.start()
    try:
        yield when
    finally:
        for p in reversed(patches):
            p.stop()


@contextmanager
def temp_project_dir():
    """
    Run inside a throwaway CWD with a data/ subdirectory.

    get_campaign() and the baseline loader both read relative paths, so tests
    that touch them must never be able to see — let alone write — the real
    data/ directory holding the live campaign.
    """
    prev = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        os.chdir(tmp)
        try:
            yield tmp
        finally:
            os.chdir(prev)


def add_trade(db, *, trade_date: date, entry_time: datetime, net_pnl: float,
              status: str = "target_hit", symbol: str = "MNQ", side: str = "long",
              qty: int = 1, exit_time: datetime | None = None,
              session: str | None = None, entry_price: float = 20000.0,
              exit_price: float = 20010.0):
    t = Trade(
        symbol=symbol, side=side, qty=qty,
        entry_price=entry_price, exit_price=exit_price,
        status=status, net_pnl=net_pnl, pnl=net_pnl,
        entry_time=entry_time,
        exit_time=exit_time or entry_time,
        trade_date=trade_date, strategy="multi_session", session=session,
    )
    db.add(t)
    db.commit()
    return t


def add_daily(db, *, on: date, bars: int = 0, signals: int = 0,
              rejected: int = 0, taken: int = 0, pnl: float = 0.0):
    row = DailyStats(
        date=on, starting_balance=50000.0, current_balance=50000.0 + pnl,
        pnl=pnl, bars_evaluated=bars, signals_generated=signals,
        signals_rejected=rejected, signals_taken=taken, trades_count=taken,
    )
    db.add(row)
    db.commit()
    return row


def add_snapshot(db, *, on: date, cycles: int, balance: float = 50000.0):
    snap = EquitySnapshot(date=on, cycles=cycles, balance=balance,
                          equity=balance, unrealized_pnl=0.0)
    db.add(snap)
    db.commit()
    return snap
