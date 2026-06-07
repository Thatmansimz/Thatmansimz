import logging
import httpx
from typing import Optional

from backend.brokers.base import BaseBroker

logger = logging.getLogger(__name__)

TRADOVATE_LIVE_URL = "https://live.tradovateapi.com/v1"
TRADOVATE_DEMO_URL = "https://demo.tradovateapi.com/v1"


class TradovateBroker(BaseBroker):
    """
    Tradovate futures broker integration.
    Supports MES, MNQ, MGC and other CME micro futures.
    Automation is allowed on Tradovate — confirm with prop firm rules first.

    Demo account: https://trader.tradovate.com (free demo)
    """

    def __init__(self, config):
        self.config = config
        self._token: Optional[str] = None
        self._account_id: Optional[int] = None
        self._base_url = TRADOVATE_DEMO_URL
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _authenticate(self):
        resp = await self._client.post(
            f"{self._base_url}/auth/accesstokenrequest",
            json={
                "name": self.config.TRADOVATE_USERNAME,
                "password": self.config.TRADOVATE_PASSWORD,
                "appId": "Sample App",
                "appVersion": "1.0",
                "cids": [9],
                "sec": "HMAC",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("accessToken")
        account_id = self.config.TRADOVATE_ACCOUNT_ID
        self._account_id = int(account_id) if account_id else None
        logger.info("Tradovate authenticated | Account: %s", self._account_id)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _ensure_auth(self):
        if not self._token:
            await self._authenticate()

    async def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> dict:
        await self._ensure_auth()

        action = "Buy" if side == "long" else "Sell"
        body = {
            "accountSpec": self.config.TRADOVATE_USERNAME,
            "accountId": self._account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": qty,
            "orderType": "Limit",
            "price": entry_price,
            "isAutomated": True,
            "bracket1": {
                "action": "Sell" if side == "long" else "Buy",
                "orderType": "Stop",
                "stopPrice": stop_price,
                "orderQty": qty,
            },
            "bracket2": {
                "action": "Sell" if side == "long" else "Buy",
                "orderType": "Limit",
                "price": target_price,
                "orderQty": qty,
            },
        }
        resp = await self._client.post(
            f"{self._base_url}/order/placebracketorder",
            headers=self._headers(),
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        order_id = str(data.get("orderId", ""))
        logger.info("Tradovate order placed: %s", order_id)
        return {"order_id": order_id, "status": "submitted", "fill_price": entry_price}

    async def get_position(self, symbol: str) -> Optional[dict]:
        await self._ensure_auth()
        try:
            resp = await self._client.get(
                f"{self._base_url}/position/list",
                headers=self._headers(),
            )
            resp.raise_for_status()
            positions = resp.json()
            for pos in positions:
                if pos.get("contractId") and symbol.upper() in str(pos.get("contractId", "")):
                    net_pos = pos.get("netPos", 0)
                    if net_pos == 0:
                        return None
                    return {
                        "symbol": symbol,
                        "qty": abs(net_pos),
                        "side": "long" if net_pos > 0 else "short",
                        "entry_price": float(pos.get("netPrice", 0)),
                        "current_price": float(pos.get("netPrice", 0)),
                        "unrealized_pnl": float(pos.get("openPL", 0)),
                    }
        except Exception as exc:
            logger.error("Tradovate get_position error: %s", exc)
        return None

    async def close_position(self, symbol: str) -> dict:
        await self._ensure_auth()
        position = await self.get_position(symbol)
        if not position:
            return {"price": 0.0, "status": "no_position"}

        action = "Sell" if position["side"] == "long" else "Buy"
        body = {
            "accountId": self._account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": position["qty"],
            "orderType": "Market",
            "isAutomated": True,
        }
        resp = await self._client.post(
            f"{self._base_url}/order/placeorder",
            headers=self._headers(),
            json=body,
        )
        resp.raise_for_status()
        return {"price": position.get("current_price", 0), "status": "closed"}

    async def get_account(self) -> dict:
        await self._ensure_auth()
        try:
            resp = await self._client.get(
                f"{self._base_url}/cashbalance/getcashbalancesnapshot",
                headers=self._headers(),
                params={"accountId": self._account_id},
            )
            resp.raise_for_status()
            data = resp.json()
            balance = float(data.get("realizedPnL", 0)) + float(data.get("initialMargin", 50000))
            return {
                "balance": balance,
                "equity": balance + float(data.get("openTradeEquity", 0)),
                "buying_power": float(data.get("availableFunds", 0)),
                "unrealized_pnl": float(data.get("openTradeEquity", 0)),
                "broker": "tradovate",
            }
        except Exception as exc:
            logger.error("Tradovate get_account error: %s", exc)
            return {}
