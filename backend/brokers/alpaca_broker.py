import logging
from typing import Optional

from backend.brokers.base import BaseBroker

logger = logging.getLogger(__name__)


class AlpacaBroker(BaseBroker):
    """
    Alpaca Markets broker integration (uses alpaca-py SDK).

    ⚠️  WRONG INSTRUMENT CLASS for this platform. Alpaca trades equities, ETFs,
    options and crypto — NOT CME futures. MES/MNQ/MGC cannot be traded here at
    all, so this broker is unusable for the V2 multi-session strategy or V1 ORB
    as configured. Kept only for a possible future equities/ETF variant.
    For futures, see TradovateBroker (own funded account) or a prop firm's own
    API (TopstepX).

    Free paper trading account: https://alpaca.markets
    """

    def __init__(self, config):
        self.config = config
        self._trading_client = None
        self._data_client = None
        self._connect()

    def _connect(self):
        try:
            from alpaca.trading.client import TradingClient
            self._trading_client = TradingClient(
                api_key=self.config.ALPACA_API_KEY,
                secret_key=self.config.ALPACA_SECRET_KEY,
                paper=("paper" in self.config.ALPACA_BASE_URL),
            )
            account = self._trading_client.get_account()
            logger.info(
                "Alpaca connected | Status: %s | Equity: $%.2f",
                account.status, float(account.equity),
            )
        except ImportError:
            logger.error("alpaca-py not installed. Run: pip3 install alpaca-py")
            self._trading_client = None
        except Exception as exc:
            logger.error("Alpaca connection failed: %s", exc)
            self._trading_client = None

    async def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> dict:
        if not self._trading_client:
            raise RuntimeError("Alpaca client not connected")

        from alpaca.trading.requests import LimitOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

        alpaca_side = OrderSide.BUY if side == "long" else OrderSide.SELL
        order_data = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=alpaca_side,
            time_in_force=TimeInForce.DAY,
            limit_price=round(entry_price, 2),
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target_price, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
        )
        order = self._trading_client.submit_order(order_data)
        logger.info("Alpaca bracket order submitted: %s", order.id)
        return {"order_id": str(order.id), "status": str(order.status), "fill_price": entry_price}

    async def get_position(self, symbol: str) -> Optional[dict]:
        if not self._trading_client:
            return None
        try:
            pos = self._trading_client.get_open_position(symbol)
            return {
                "symbol": symbol,
                "qty": int(float(pos.qty)),
                "side": "long" if float(pos.qty) > 0 else "short",
                "entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "unrealized_pnl": float(pos.unrealized_pl),
            }
        except Exception:
            return None

    async def close_position(self, symbol: str) -> dict:
        if not self._trading_client:
            raise RuntimeError("Alpaca client not connected")
        try:
            response = self._trading_client.close_position(symbol)
            return {"price": float(response.filled_avg_price or 0), "status": "closed"}
        except Exception as exc:
            logger.error("Failed to close %s: %s", symbol, exc)
            raise

    async def get_account(self) -> dict:
        if not self._trading_client:
            return {}
        acc = self._trading_client.get_account()
        return {
            "balance": float(acc.cash),
            "equity": float(acc.equity),
            "buying_power": float(acc.buying_power),
            "unrealized_pnl": float(acc.unrealized_pl),
            "broker": "alpaca",
        }

    async def cancel_order(self, order_id: str) -> bool:
        if not self._trading_client:
            return False
        try:
            self._trading_client.cancel_order_by_id(order_id)
            return True
        except Exception:
            return False
