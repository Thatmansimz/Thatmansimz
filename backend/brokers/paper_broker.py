import json
import os
import uuid
import logging
import tempfile
from typing import Optional
from datetime import datetime

from backend.brokers.base import BaseBroker
from backend.services.costs import slip_entry, slip_stop_exit

logger = logging.getLogger(__name__)

# Paper account state survives restarts — a 60-day forward test cannot afford
# to lose its balance and open positions every time the backend bounces.
STATE_PATH = os.path.join("data", "paper_state.json")

DEFAULT_BALANCE = 50000.0


def _load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
        return {
            "balance": float(state.get("balance", DEFAULT_BALANCE)),
            "positions": dict(state.get("positions", {})),
            "orders": dict(state.get("orders", {})),
        }
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {"balance": DEFAULT_BALANCE, "positions": {}, "orders": {}}


class PaperBroker(BaseBroker):
    """
    In-process paper trading broker. No external API calls for order routing,
    but position monitoring is driven by REAL market prices (via MarketDataService)
    so paper outcomes reflect the actual market — not a random walk.

    Honesty model:
      • Entries fill with SLIPPAGE_TICKS of adverse slippage (market order).
      • Stop exits fill through the stop by SLIPPAGE_TICKS (stops become
        market orders when touched).
      • Target exits fill exactly at the target (resting limit order).
      • Balance, open positions, and fills persist to data/paper_state.json
        so restarts never wipe the forward-test track record.
    """

    def __init__(self, config):
        self.config = config
        state = _load_state()
        self._balance = state["balance"]
        self._positions = state["positions"]
        self._orders = state["orders"]
        if self._positions:
            logger.info("[PAPER] Restored %d open position(s) from disk: %s",
                        len(self._positions), ", ".join(self._positions))
        # Live price source for honest paper fills.
        from backend.services.market_data import MarketDataService
        self.market_data = MarketDataService()

    def _save(self):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        # Write-then-rename so a crash mid-write can't corrupt the state file.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE_PATH), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({
                    "balance": self._balance,
                    "positions": self._positions,
                    "orders": self._orders,
                    "saved_at": datetime.utcnow().isoformat(),
                }, f, indent=2)
            os.replace(tmp, STATE_PATH)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def realize_pnl(self, net_pnl: float):
        """Called by the execution layer when a trade closes — moves the balance."""
        self._balance += net_pnl
        self._save()

    async def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> dict:
        order_id = str(uuid.uuid4())[:8]
        slip_ticks = int(getattr(self.config, "SLIPPAGE_TICKS", 1))
        fill_price = round(slip_entry(symbol, side, entry_price, slip_ticks), 2)

        self._positions[symbol] = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "entry_price": fill_price,
            "current_price": fill_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "order_id": order_id,
            "opened_at": datetime.utcnow().isoformat(),
        }
        self._orders[order_id] = {"order_id": order_id, "price": fill_price, "status": "filled"}
        self._save()

        logger.info(
            "[PAPER] Bracket order filled: %s %s x%d @ %.2f (signal %.2f, %d-tick slip) | SL: %.2f | TP: %.2f",
            side.upper(), symbol, qty, fill_price, entry_price, slip_ticks,
            stop_price, target_price,
        )
        return {"order_id": order_id, "fill_price": fill_price, "status": "filled"}

    async def get_position(self, symbol: str) -> Optional[dict]:
        pos = self._positions.get(symbol)
        if not pos:
            return None

        # Pull a REAL current price from the market instead of a random walk.
        # Fall back to the last known price if the feed is briefly unavailable.
        try:
            price = self.market_data.get_latest_price(symbol)
        except Exception:
            price = None
        if not price or price <= 0:
            price = pos["current_price"]
        current = round(float(price), 2)
        pos["current_price"] = current

        target = pos["target_price"]
        stop = pos["stop_price"]
        slip_ticks = int(getattr(self.config, "SLIPPAGE_TICKS", 1))

        # Check if the live price has crossed the bracket's stop or target.
        # Stops fill through the level (market order); targets fill at price
        # (resting limit). The exit fill is recorded so the execution layer
        # reconciles a truthful P&L (get_last_fill returns this exit price).
        hit = None
        if pos["side"] == "long":
            if current <= stop:
                hit = slip_stop_exit(symbol, "long", stop, slip_ticks)
            elif current >= target:
                hit = target
        else:
            if current >= stop:
                hit = slip_stop_exit(symbol, "short", stop, slip_ticks)
            elif current <= target:
                hit = target

        if hit is not None:
            self._orders[pos["order_id"]] = {
                "order_id": pos["order_id"], "price": round(float(hit), 2),
                "status": "filled", "exit": True,
            }
            del self._positions[symbol]
            self._save()
            return None

        self._save()
        return {**pos, "current_price": current}

    async def close_position(self, symbol: str) -> dict:
        pos = self._positions.pop(symbol, None)
        if not pos:
            return {"price": 0.0, "status": "no_position"}

        # Manual/EOD close is a market order — slip it like one.
        slip_ticks = int(getattr(self.config, "SLIPPAGE_TICKS", 1))
        exit_side = "long" if pos["side"] == "long" else "short"
        fill_price = round(
            slip_stop_exit(symbol, exit_side, pos["current_price"], slip_ticks), 2
        )
        self._save()
        logger.info("[PAPER] Closed %s @ %.2f", symbol, fill_price)
        return {"price": fill_price, "status": "filled"}

    async def get_account(self) -> dict:
        from backend.services.risk_manager import POINT_VALUES
        total_unrealized = 0.0
        for pos in self._positions.values():
            entry = pos["entry_price"]
            current = pos["current_price"]
            qty = pos["qty"]
            pv = POINT_VALUES.get(pos["symbol"].upper(), 5.0)
            if pos["side"] == "long":
                total_unrealized += (current - entry) * pv * qty
            else:
                total_unrealized += (entry - current) * pv * qty

        return {
            "balance": self._balance,
            "equity": self._balance + total_unrealized,
            "buying_power": self._balance * 10,
            "unrealized_pnl": total_unrealized,
            "broker": "paper",
        }

    async def get_last_fill(self, order_id: str) -> Optional[dict]:
        return self._orders.get(order_id)

    async def update_stop(self, order_id: str, new_stop: float) -> bool:
        for pos in self._positions.values():
            if pos.get("order_id") == order_id:
                pos["stop_price"] = new_stop
                self._save()
                return True
        return False
