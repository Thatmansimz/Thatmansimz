from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List, Optional
import json


class Settings(BaseSettings):
    # Broker configuration
    BROKER: str = "paper"  # "alpaca" | "tradovate" | "paper"

    # Alpaca credentials
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"

    # Tradovate credentials
    TRADOVATE_USERNAME: str = ""
    TRADOVATE_PASSWORD: str = ""
    TRADOVATE_ACCOUNT_ID: str = ""

    # Symbols to trade
    SYMBOLS: List[str] = ["MES", "MNQ"]

    # Trading flags
    TRADING_ENABLED: bool = False

    # Prop firm selection
    PROP_FIRM: str = "none"  # "none" | "apex" | "topstep" | "traderfi" | "myforexfunds"

    # Prop firm rule overrides (set via env or derived from PROP_FIRM)
    PROP_FIRM_ACCOUNT_SIZE: float = 50000.0
    PROP_FIRM_DAILY_LOSS_LIMIT: float = 2000.0
    PROP_FIRM_MAX_DRAWDOWN: float = 3000.0
    PROP_FIRM_PROFIT_TARGET: float = 3000.0

    # AI settings
    AI_CONFIDENCE_THRESHOLD: float = 0.65
    MIN_RISK_REWARD_RATIO: float = 2.0

    # Risk management
    MAX_STOP_LOSS_DOLLARS: float = 250.0
    DAILY_PROFIT_TARGET_DOLLARS: float = 1000.0
    MAX_CONCURRENT_TRADES: int = 3
    RISK_PER_TRADE_PERCENT: float = 1.0

    # Database
    DATABASE_URL: str = "sqlite:///./data/trading.db"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    @field_validator("SYMBOLS", mode="before")
    @classmethod
    def parse_symbols(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [s.strip() for s in v.split(",")]
        return v

    def get_prop_firm_rules(self) -> dict:
        """Return prop firm rules based on selected firm."""
        rules_map = {
            "none": {
                "name": "None",
                "daily_loss_limit": self.PROP_FIRM_DAILY_LOSS_LIMIT,
                "max_drawdown": self.PROP_FIRM_MAX_DRAWDOWN,
                "profit_target": self.PROP_FIRM_PROFIT_TARGET,
                "account_size": self.PROP_FIRM_ACCOUNT_SIZE,
                "trailing_drawdown": False,
                "allows_automation": True,
                "days_to_complete": None,
            },
            "apex": {
                "name": "Apex Trader Funding",
                "daily_loss_limit": 2500.0,
                "max_drawdown": 2500.0,
                "profit_target": 3000.0,
                "account_size": 50000.0,
                "trailing_drawdown": False,
                "allows_automation": True,
                "days_to_complete": None,
                "notes": "Static drawdown, no time limit, automation allowed",
            },
            "topstep": {
                "name": "TopStep",
                "daily_loss_limit": 1000.0,
                "max_drawdown": 2000.0,
                "profit_target": 3000.0,
                "account_size": 50000.0,
                "trailing_drawdown": True,
                "allows_automation": False,
                "days_to_complete": None,
                "notes": "Trailing drawdown, NO automation allowed - manual only",
            },
            "traderfi": {
                "name": "TraderFi",
                "daily_loss_limit": 2000.0,
                "max_drawdown": 3000.0,
                "profit_target": 3000.0,
                "account_size": 50000.0,
                "trailing_drawdown": False,
                "allows_automation": True,
                "days_to_complete": None,
                "notes": "Instant funded, automation allowed",
            },
            "myforexfunds": {
                "name": "MyFundedFutures",
                "daily_loss_limit": 1500.0,
                "max_drawdown": 3000.0,
                "profit_target": 4000.0,
                "account_size": 50000.0,
                "trailing_drawdown": False,
                "allows_automation": True,
                "days_to_complete": 30,
                "notes": "30-day evaluation, automation allowed",
            },
        }
        firm_key = self.PROP_FIRM.lower()
        rules = rules_map.get(firm_key, rules_map["none"])

        # Allow env overrides for custom firms
        if self.PROP_FIRM_DAILY_LOSS_LIMIT != 2000.0:
            rules["daily_loss_limit"] = self.PROP_FIRM_DAILY_LOSS_LIMIT
        if self.PROP_FIRM_MAX_DRAWDOWN != 3000.0:
            rules["max_drawdown"] = self.PROP_FIRM_MAX_DRAWDOWN
        if self.PROP_FIRM_PROFIT_TARGET != 3000.0:
            rules["profit_target"] = self.PROP_FIRM_PROFIT_TARGET
        if self.PROP_FIRM_ACCOUNT_SIZE != 50000.0:
            rules["account_size"] = self.PROP_FIRM_ACCOUNT_SIZE

        return rules

    # Futures contract specs
    FUTURES_SPECS: dict = {
        "MES": {
            "tick_size": 0.25,
            "tick_value": 1.25,
            "point_value": 5.0,
            "margin": 40.0,
            "description": "Micro E-mini S&P 500",
        },
        "MNQ": {
            "tick_size": 0.25,
            "tick_value": 0.50,
            "point_value": 2.0,
            "margin": 40.0,
            "description": "Micro E-mini Nasdaq-100",
        },
        "MGC": {
            "tick_size": 0.10,
            "tick_value": 1.00,
            "point_value": 10.0,
            "margin": 100.0,
            "description": "Micro Gold",
        },
    }

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
