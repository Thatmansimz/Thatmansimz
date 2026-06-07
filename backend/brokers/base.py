from abc import ABC, abstractmethod
from typing import Optional


class BaseBroker(ABC):
    @abstractmethod
    async def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> dict:
        """Submit entry order with attached stop-loss and take-profit."""

    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[dict]:
        """Return current open position for symbol or None."""

    @abstractmethod
    async def close_position(self, symbol: str) -> dict:
        """Market-close an open position. Returns fill info."""

    @abstractmethod
    async def get_account(self) -> dict:
        """Return account balance and equity."""

    async def get_last_fill(self, order_id: str) -> Optional[dict]:
        return None

    async def update_stop(self, order_id: str, new_stop: float) -> bool:
        return False

    async def cancel_order(self, order_id: str) -> bool:
        return False
