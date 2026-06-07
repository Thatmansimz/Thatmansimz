from backend.brokers.base import BaseBroker
from backend.brokers.paper_broker import PaperBroker
from backend.brokers.alpaca_broker import AlpacaBroker
from backend.brokers.tradovate_broker import TradovateBroker

__all__ = ["BaseBroker", "PaperBroker", "AlpacaBroker", "TradovateBroker"]


def get_broker(broker_name: str, config) -> BaseBroker:
    name = broker_name.lower()
    if name == "alpaca":
        return AlpacaBroker(config)
    if name == "tradovate":
        return TradovateBroker(config)
    return PaperBroker(config)
