"""Synthetic regressions. No market downloads, broker credentials or live DB."""
import asyncio
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from tests.support import temp_project_dir, make_session
from backend.brokers import get_broker
from backend.brokers.paper_broker import PaperBroker
from backend.config import Settings
from backend.services.ai_engine import AIEngine
from backend.services.execution import ExecutionService
from backend.services.exit_rules import trail_v2


class ExecutionRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = temp_project_dir(); self.tmp.__enter__()
        self.broker = PaperBroker(Settings(_env_file=None))
        self.broker.market_data = SimpleNamespace(get_completed_bars_since=lambda *a: [])

    async def asyncTearDown(self):
        self.tmp.__exit__(None, None, None)

    async def open_position(self, opened=None):
        opened = opened or datetime(2020, 1, 1, 10)
        with patch("backend.brokers.paper_broker.utc_now", return_value=opened):
            return await self.broker.submit_bracket_order("MNQ", 1, "long", 100, 90, 120)

    def bars(self, rows):
        self.broker.market_data.get_completed_bars_since = lambda *a: rows

    async def test_pre_entry_bar_cannot_exit_new_order(self):
        await self.open_position(datetime(2020, 1, 1, 10, 2))
        self.bars([dict(ts="2020-01-01T10:00:00Z", open=100, high=105, low=80, close=95)])
        self.assertIsNotNone(await self.broker.get_position("MNQ"))
        self.assertNotIn("last_bar_ts", self.broker._positions["MNQ"])

    async def test_replay_missed_bars_exits_on_first_eligible_touch(self):
        await self.open_position()
        self.bars([dict(ts="2020-01-01T10:10:00Z", open=95, high=123, low=94, close=121),
                   dict(ts="2020-01-01T10:00:00Z", open=100, high=101, low=89, close=100)])
        self.assertIsNone(await self.broker.get_position("MNQ"))
        self.assertEqual(next(iter(self.broker._orders.values()))["cause"], "stop")

    async def test_duplicate_bar_cannot_trigger_a_later_stop(self):
        order = await self.open_position()
        self.bars([dict(ts="2020-01-01T10:00:00Z", open=100, high=101, low=99, close=100)])
        await self.broker.get_position("MNQ")
        await self.broker.update_stop(order["order_id"], 100)
        self.assertIsNotNone(await self.broker.get_position("MNQ"))

    async def test_gap_through_stop_fills_at_adverse_open(self):
        await self.open_position()
        self.bars([dict(ts="2020-01-01T10:00:00Z", open=85, high=88, low=84, close=86)])
        await self.broker.get_position("MNQ")
        self.assertEqual(next(iter(self.broker._orders.values()))["price"], 84.75)

    async def test_unexplained_gap_is_visible(self):
        await self.open_position()
        self.bars([dict(ts="2020-01-01T10:20:00Z", open=100, high=101, low=99, close=100)])
        self.assertIn("reconciliation_required", await self.broker.get_position("MNQ"))

    async def test_rejected_stop_does_not_change_local_stop(self):
        risk = Mock(); risk.minutes_until_close.return_value = 99
        broker = Mock(); broker.get_position = AsyncMock(return_value={"current_price": 111})
        broker.update_stop = AsyncMock(return_value=False)
        service = ExecutionService(broker, risk, Mock())
        service._trailing_stop_v2 = Mock(return_value=101)
        trade = SimpleNamespace(id=1, symbol="MNQ", side="long", entry_price=100, initial_stop_loss=90,
                                stop_loss=90, strategy="multi_session", broker_order_id="x", qty=1)
        await service._check_trade(trade)
        self.assertEqual(trade.stop_loss, 90)

    async def test_corrupt_paper_state_does_not_reset_balance(self):
        with open("data/paper_state.json", "w") as f: f.write("broken")
        with self.assertRaises(json.JSONDecodeError): PaperBroker(Settings(_env_file=None))

    async def test_exit_with_missing_history_is_not_finalized(self):
        broker = Mock()
        broker.get_last_fill = AsyncMock(return_value={"exit": True, "price": 90, "reconciliation_required": "missing events"})
        service = ExecutionService(broker, Mock(), Mock())
        service._finalize_trade = AsyncMock()
        await service._reconcile_closed_trade(SimpleNamespace(id=1, broker_order_id="x"))
        service._finalize_trade.assert_not_awaited()


class StrategyRegressions(unittest.TestCase):
    def test_trail_starts_at_one_r_both_sides(self):
        for side, initial, below, trigger, ema in [("long", 90, 102, 110, 100), ("short", 110, 98, 90, 100)]:
            with self.subTest(side=side):
                self.assertEqual(trail_v2("MNQ", side, 100, initial, initial, below, ema), initial)
                self.assertEqual(trail_v2("MNQ", side, 100, initial, initial, trigger, ema), 100)

    def test_active_trail_never_widens_and_obeys_tick(self):
        self.assertEqual(trail_v2("MNQ", "long", 100, 90, 101, 111, 104.13), 104)
        self.assertEqual(trail_v2("MNQ", "long", 100, 90, 104, 103, 102), 104)
        self.assertEqual(trail_v2("MNQ", "short", 100, 110, 99, 89, 95.87), 96)

    def test_falling_and_rising_series_have_symmetric_labels(self):
        engine = AIEngine.__new__(AIEngine)
        for sign in [-1, 1]:
            df = pd.DataFrame({"close": 100 * (1 + sign * .01) ** np.arange(20)})
            labels = engine._label_trades(df)
            self.assertTrue((labels.iloc[:-6] == sign).all())
            self.assertTrue(labels.iloc[-6:].isna().all())

    def test_unverified_brokers_are_rejected(self):
        for name in ["tradovate", "alpaca", "unknown"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                get_broker(name, Settings(_env_file=None))


class ApiGates(unittest.TestCase):
    def setUp(self):
        from backend import main
        self.main = main
        self.client = TestClient(main.app)

    def test_mutations_require_token_and_cannot_arm(self):
        with patch.object(self.main.settings, "API_TOKEN", ""):
            self.assertEqual(self.client.post("/api/trading/start").status_code, 503)
        with patch.object(self.main.settings, "API_TOKEN", "test-only"):
            self.assertEqual(self.client.post("/api/trading/start").status_code, 401)
            response = self.client.post("/api/trading/start", headers={"Authorization": "Bearer test-only"})
            self.assertEqual(response.status_code, 409)
            self.assertFalse(response.json()["detail"]["live_pilot_available"])
            for path in ["begin", "run", "reset"]:
                response = self.client.post(f"/api/forward-test/{path}?force=true", headers={"Authorization": "Bearer test-only"})
                self.assertEqual(response.status_code, 409)

    def test_direct_adapter_submission_is_blocked(self):
        from backend.brokers.alpaca_broker import AlpacaBroker
        from backend.brokers.tradovate_broker import TradovateBroker
        for cls in [AlpacaBroker, TradovateBroker]:
            with self.subTest(adapter=cls.__name__), self.assertRaises(ValueError):
                asyncio.run(cls.__new__(cls).submit_bracket_order("MNQ", 1, "long", 100, 90, 120))

    def test_workspace_reads_isolated_records(self):
        from backend.database import get_db
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        from sqlalchemy.orm import sessionmaker
        from backend.models.trade import Base
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        self.main.app.dependency_overrides[get_db] = lambda: db
        try:
            response = self.client.get("/api/workspace")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["closed_trades"], 0)
            self.assertEqual(response.json()["readiness"]["verified_gates"], 0)
        finally:
            self.main.app.dependency_overrides.pop(get_db, None); db.close()
