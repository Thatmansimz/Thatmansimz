import logging
from typing import Optional

from backend.brokers.base import BaseBroker

logger = logging.getLogger(__name__)


class AlpacaBroker(BaseBroker):
    """
    Alpaca Markets broker integration.
    Supports paper trading via ALPACA_BASE_URL=https://paper-api.alpaca.markets
    Free paper trading account: https://alpaca.markets
    """

    def __init__(self, config):
        self.config = config
        self._client = None
        self._connect()

    def _connect(self):
        try:
            import alpaca_trade_api as tradeapi
            self._client = tradeapi.REST(
                key_id=self.config.ALPACA_API_KEY,
                secret_key=self.config.ALPACA_SECRET_KEY,
                base_url=self.config.ALPACA_BASE_URL,
            )
            account = self._client.get_account()
            logger.info(
                "Alpaca connected | Status: %s | Balance: $%.2f",
                account.status, float(account.equity),
            )
        except ImportError:
            logger.error("alpaca-trade-api not installed. Run: pip install alpaca-trade-api")
            self._client = None
        except Exception as exc:
            logger.error("Alpaca connection failed: %s", exc)
            self._client = None

    async def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> dict:
        if not self._client:
            raise RuntimeError("Alpaca client not connected")

        alpaca_side = "buy" if side == "long" else "sell"
        order = self._client.submit_order(
            symbol=symbol,
            qty=qty,
            side=alpaca_side,
            type="limit",
            time_in_force="day",
            limit_price=str(round(entry_price, 2)),
            order_class="bracket",
            stop_loss={"stop_price": str(round(stop_price, 2))},
            take_profit={"limit_price": str(round(target_price, 2))},
        )
        logger.info("Alpaca bracket order submitted: %s", order.id)
        return {"order_id": order.id, "status": order.status, "fill_price": entry_price}

    async def get_position(self, symbol: str) -> Optional[dict]:
        if not self._client:
            return None
        try:
            pos = self._client.get_position(symbol)
            return {
                "symbol": symbol,
                "qty": int(pos.qty),
                "side": "long" if float(pos.qty) > 0 else "short",
                "entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "unrealized_pnl": float(pos.unrealized_pl),
            }
        except Exception:
            return None

    async def close_position(self, symbol: str) -> dict:
        if not self._client:
            raise RuntimeError("Alpaca client not connected")
        try:
            order = self._client.close_position(symbol)
            return {"price": float(order.filled_avg_price or 0), "status": "closed"}
        except Exception as exc:
            logger.error("Failed to close %s: %s", symbol, exc)
            raise

    async def get_account(self) -> dict:
        if not self._client:
            return {}
        acc = self._client.get_account()
        return {
            "balance": float(acc.cash),
            "equity": float(acc.equity),
            "buying_power": float(acc.buying_power),
            "unrealized_pnl": float(acc.unrealized_pl),
            "broker": "alpaca",
        }

    async def cancel_order(self, order_id: str) -> bool:
        if not self._client:
            return False
        try:
            self._client.cancel_order(order_id)
            return True
        except Exception:
            return False
