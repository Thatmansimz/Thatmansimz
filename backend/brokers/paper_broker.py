import uuid
import logging
from typing import Optional
from datetime import datetime

from backend.brokers.base import BaseBroker

logger = logging.getLogger(__name__)

_open_positions: dict[str, dict] = {}
_orders: dict[str, dict] = {}


class PaperBroker(BaseBroker):
    """
    In-process paper trading broker. No external API calls.
    Fills orders immediately at the provided price (no slippage simulation).
    """

    def __init__(self, config):
        self.config = config
        self._balance = 50000.0

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
        fill_price = entry_price

        _open_positions[symbol] = {
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
        _orders[order_id] = {"order_id": order_id, "price": fill_price, "status": "filled"}

        logger.info(
            "[PAPER] Bracket order filled: %s %s x%d @ %.2f | SL: %.2f | TP: %.2f",
            side.upper(), symbol, qty, fill_price, stop_price, target_price,
        )
        return {"order_id": order_id, "fill_price": fill_price, "status": "filled"}

    async def get_position(self, symbol: str) -> Optional[dict]:
        pos = _open_positions.get(symbol)
        if not pos:
            return None

        # Simulate price movement toward target or stop (50/50 paper simulation)
        import random
        current = pos["current_price"]
        entry = pos["entry_price"]
        target = pos["target_price"]
        stop = pos["stop_price"]

        # Small drift each call
        direction = 1 if pos["side"] == "long" else -1
        drift = current * random.uniform(-0.001, 0.002) * direction
        current = round(current + drift, 2)
        pos["current_price"] = current

        # Check if stop or target has been hit
        if pos["side"] == "long":
            if current <= stop:
                del _open_positions[symbol]
                return None
            if current >= target:
                del _open_positions[symbol]
                return None
        else:
            if current >= stop:
                del _open_positions[symbol]
                return None
            if current <= target:
                del _open_positions[symbol]
                return None

        return {**pos, "current_price": current}

    async def close_position(self, symbol: str) -> dict:
        pos = _open_positions.pop(symbol, None)
        if not pos:
            return {"price": 0.0, "status": "no_position"}

        fill_price = pos["current_price"]
        logger.info("[PAPER] Closed %s @ %.2f", symbol, fill_price)
        return {"price": fill_price, "status": "filled"}

    async def get_account(self) -> dict:
        total_unrealized = 0.0
        for pos in _open_positions.values():
            entry = pos["entry_price"]
            current = pos["current_price"]
            qty = pos["qty"]
            pv = 5.0
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
        return _orders.get(order_id)

    async def update_stop(self, order_id: str, new_stop: float) -> bool:
        for pos in _open_positions.values():
            if pos.get("order_id") == order_id:
                pos["stop_price"] = new_stop
                return True
        return False
