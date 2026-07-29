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
    # ORB validated at 1R targets — keep the min R:R gate at 1.0 so they pass.
    MIN_RISK_REWARD_RATIO: float = 1.0

    # ── V2 configuration (research-driven) ──
    # Which sessions the V2 engine is allowed to trade. Research on 60d/171
    # trades: ALL sessions = PF 0.92 (-$3,411); LONDON -$3,842 and ASIA -$1,328
    # were the bleeders; NEW_YORK was the only positive session (+$1,759).
    V2_SESSIONS: List[str] = ["ASIA", "LONDON", "NEW_YORK"]
    # Target as a multiple of risk. 0 = use each session's own max_rr (2.0).
    # Research: 3.0R was the best target across a 2.5-3.5R plateau, improving
    # the full 60d period by ~$3,050 vs 2.0R. Mechanism: a bigger target lowers
    # the break-even win rate (33.8% at 2R -> 25.4% at 3R) and spreads fixed
    # per-contract commission over a larger win.
    V2_TARGET_RR: float = 0.0
    # Fixed dollar risk per trade. 0 = V2's default "profit window" sizing,
    # which sizes INVERSELY to stop width and produced a $6,534 max drawdown —
    # 2-3x every prop firm's limit. Set this to derive size from the drawdown
    # budget instead of from a profit target.
    V2_RISK_PER_TRADE: float = 0.0

    # Active strategy: "orb" | "momentum" | "ml" | "multi_session" (V2)
    # NOTE: "orb" remains the validated default. "multi_session" is the V2
    # business-partner engine — opt in explicitly via STRATEGY=multi_session.
    STRATEGY: str = "orb"

    # Red-folder (high-impact) news filter
    NEWS_FILTER_ENABLED: bool = True
    NEWS_BLACKOUT_PRE_MIN: int = 15
    NEWS_BLACKOUT_POST_MIN: int = 15
    NEWS_CALENDAR_PATH: str = "data/news_calendar.json"

    # Risk management
    # NOTE: MAX_STOP_LOSS_DOLLARS is V1 ORB's risk budget (it sizes TO this).
    # V2 multi_session sizes to a $500–1500 profit window instead, which puts
    # its risk in the $400–1000 band; it is capped by V2_MAX_RISK_DOLLARS so
    # the V1 budget cannot silently veto every V2 signal.
    V2_MAX_RISK_DOLLARS: float = 1100.0
    MAX_STOP_LOSS_DOLLARS: float = 250.0
    DAILY_PROFIT_TARGET_DOLLARS: float = 1000.0
    MAX_CONCURRENT_TRADES: int = 3
    RISK_PER_TRADE_PERCENT: float = 1.0

    # Trading friction (applied to paper fills AND backtests so P&L is honest)
    COMMISSION_PER_SIDE: float = 1.50   # $/contract per side → $3.00 round trip
    SLIPPAGE_TICKS: int = 1             # ticks of adverse fill on entry + stop exits

    # Forward-test campaign length (days) for the live paper track record
    FORWARD_TEST_TARGET_DAYS: int = 60

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
                # UPDATED 2026-07-29 (was False — that predated TopstepX).
                # TopstepX launched its own API in late April 2026 and now
                # permits automation in BOTH the Trading Combine (evaluation)
                # and funded accounts. ~$29/mo for API access.
                # HARD CONSTRAINT: Topstep's Terms require all trading activity
                # to originate from your PERSONAL DEVICE — VPS, VPN and remote
                # servers are prohibited. This engine must therefore keep
                # running on the Mac; it can never be moved to a cloud host.
                "allows_automation": True,
                "days_to_complete": None,
                "notes": "Trailing drawdown. TopstepX API automation allowed "
                         "(eval + funded). Personal device only — no VPS/VPN.",
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
        "NQ": {
            "tick_size": 0.25,
            "tick_value": 5.0,
            "point_value": 20.0,
            "margin": 1800.0,
            "description": "E-mini Nasdaq-100 (V2 full-size)",
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
