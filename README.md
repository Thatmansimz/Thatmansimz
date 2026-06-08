# Tajari AI Trading

Autonomous AI-powered day trading platform — scans markets, generates high-probability setups using machine learning, and executes orders automatically during market hours. Built for prop firm evaluations and funded accounts.

---

## What It Does

- **AI Signal Engine** — Gradient Boosting model trained on 25+ technical indicators (RSI, MACD, Bollinger Bands, ATR, ADX, VWAP, volume, EMA alignment, candlestick patterns) identifies long/short setups with confidence scores
- **Autonomous Trading Loop** — Scans symbols every 60 seconds during market hours, executes bracket orders (entry + stop + target) without human input
- **Risk Manager** — Enforces $250 max stop loss per trade, daily loss limits, daily profit targets, and prop firm-specific rules
- **Prop Firm Rules Engine** — Pre-configured for Apex, TraderFi, MyFundedFutures. Automatically pauses trading when you hit daily limits
- **Live Dashboard** — Real-time P&L, open positions, AI signals with confidence meters, evaluation progress bars
- **Paper Trading** — Test everything with zero risk using Alpaca's free paper trading API before going live

---

## Prop Firm Compatibility

| Firm | AI/Automation | Account Size | Daily Loss | Profit Target | Notes |
|------|--------------|-------------|------------|---------------|-------|
| **Apex Trader Funding** | YES | $50k | $2,500 | $3,000 | Static drawdown, no time limit |
| **TraderFi** | YES | $50k | $2,000 | $3,000 | Instant funded option |
| **MyFundedFutures** | YES | $50k | $1,500 | $4,000 | 30-day evaluation |
| **Tradovate** | YES | — | — | — | Broker, not prop firm. Use with above |
| **TopStep** | NO | $50k | $1,000 | $3,000 | Manual trading only — do NOT automate |

**Why micro futures (MES/MNQ)?** Low margin requirements (~$40/contract), tight spreads, active 24/5, and $250 stop loss is easily achievable with 1-3 contracts.

---

## Quick Start

### 1. Clone & Install
```bash
git clone <repo>
cd ai-trading-platform
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env — set BROKER=paper to start safely
```

### 3. Train the AI Models
```bash
python scripts/train_model.py --symbols MES MNQ --period 60d
```

### 4. Run Backtest (verify it works before going live)
```bash
python scripts/backtest.py --symbol MES --period 30d
```

### 5. Start the Backend
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Start the Dashboard
```bash
cd frontend
npm install
npm run dev
```

### View the app

| What | URL |
|------|-----|
| **Dashboard (the cool UI)** | **http://localhost:3000** |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

> The dashboard is the main event — open **http://localhost:3000** in your browser.

---

## Docker (Full Stack)
```bash
cp .env.example .env
docker-compose up --build
# Backend: http://localhost:8000
# Dashboard: http://localhost:3000
```

---

## Configuration

Key `.env` settings:

```env
BROKER=paper                    # paper | alpaca | tradovate
TRADING_ENABLED=false           # Set true to enable auto-trading
PROP_FIRM=apex                  # none | apex | traderfi | myforexfunds

# Risk limits
MAX_STOP_LOSS_DOLLARS=250       # Max loss per trade ($)
DAILY_PROFIT_TARGET_DOLLARS=1000 # Stop trading after hitting this
AI_CONFIDENCE_THRESHOLD=0.65   # Minimum AI confidence to take trade (0-1)
MIN_RISK_REWARD_RATIO=2.0       # Minimum R:R before taking trade
MAX_CONCURRENT_TRADES=3         # Max open positions at once
RISK_PER_TRADE_PERCENT=1.0      # % of account to risk per trade

# Prop firm limits (auto-set by PROP_FIRM, or override manually)
PROP_FIRM_ACCOUNT_SIZE=50000
PROP_FIRM_DAILY_LOSS_LIMIT=2500
PROP_FIRM_MAX_DRAWDOWN=2500
PROP_FIRM_PROFIT_TARGET=3000
```

---

## Broker Setup

### Paper Trading (Free — Start Here)
1. Sign up at [alpaca.markets](https://alpaca.markets) — free account
2. Go to Paper Trading → Get API keys
3. Set in `.env`:
   ```
   BROKER=alpaca
   ALPACA_API_KEY=your_key
   ALPACA_SECRET_KEY=your_secret
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ```

### Tradovate (Futures — for MES/MNQ)
1. Sign up at [trader.tradovate.com](https://trader.tradovate.com) — free demo
2. Set in `.env`:
   ```
   BROKER=tradovate
   TRADOVATE_USERNAME=your_email
   TRADOVATE_PASSWORD=your_password
   ```

### Apex Prop Firm (Funded Account)
1. Sign up at [apextraderfunding.com](https://apextraderfunding.com)
2. Choose a $50k evaluation (~$167/month or one-time)
3. Rules: Make $3,000 profit, max $2,500 daily loss, static drawdown
4. Use Tradovate as your broker (Apex is compatible)
5. **Automation is allowed** — this platform is built for it

---

## How the AI Works

```
Market Data (yfinance) 
    → 25+ Technical Indicators (RSI, MACD, ATR, ADX, Bollinger, Stochastic, etc.)
    → Feature Engineering (price position vs EMAs, volume ratios, candle patterns, time-of-day)
    → Gradient Boosting Classifier
    → Probability Scores (Long / Short / Neutral)
    → Confidence Filter (>65% required)
    → Risk Validation ($250 max stop, 2:1 R:R minimum)
    → Bracket Order Execution (entry + stop + target in one order)
```

The model is trained on labeled historical data:
- **Long signal (1)**: Price rises >0.5% before falling 0.25% in next 6 bars
- **Short signal (-1)**: Price falls >0.5% before rising 0.25% in next 6 bars
- **Neutral (0)**: Neither condition met

---

## Daily P&L Math

With a $50,000 funded account on Apex:

| Setup | Details |
|-------|---------|
| Target | $1,000/day = 2% daily return |
| Instrument | MES (Micro E-mini S&P 500, $5/point) |
| Stop loss | 10 points × $5 = $50/contract |
| Target | 30 points × $5 = $150/contract |
| R:R | 3:1 |
| Contracts | 3 MES contracts |
| Risk/trade | $150 (well under $250 limit) |
| Win scenario | $450 per winning trade |
| Trades needed | ~3 winning trades/day to hit $1k |

With a 60%+ win rate (the model's target), you need roughly 5 trades/day.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | System status, market hours, AI status |
| GET | `/api/account` | Account balance, daily P&L |
| GET | `/api/trades/today` | Today's trade list |
| GET | `/api/signals` | Recent AI signals |
| GET | `/api/stats/performance` | Win rate, profit factor, avg win/loss |
| GET | `/api/prop-firm/status` | Evaluation progress |
| POST | `/api/trading/start` | Enable auto-trading |
| POST | `/api/trading/stop` | Disable auto-trading |
| POST | `/api/trading/close-all` | Emergency close all positions |
| POST | `/api/ai/train?symbol=MES` | Train/retrain AI model |
| POST | `/api/backtest?symbol=MES` | Run backtest |
| WS | `/ws/live` | Live P&L and trade updates |

---

## V2 — Multi-Session Engine (NQ / MNQ) — *Business Partner Strategy*

> **V2 is fully isolated from V1.** It lives in its own package
> (`backend/strategies/v2/`) and is **never the default**. Your validated V1
> ORB code is untouched. Opt in with `STRATEGY=multi_session`.

A 24/5 engine that trades **NQ** (E-mini, $20/pt) and **MNQ** (Micro, $2/pt)
across all three global sessions, using a strict **two-indications** filter.

### How V2 thinks (the spec, in order)

1. **Sessions & kill zones** (`v2/sessions.py`) — identifies the active session
   (Asia / London / New York), its peak-volatility "kill zone", and the
   London↔NY overlap. Skips the first 5 min of each kill zone (volatility pause).
   In the 09:00–12:00 overlap, NY structural levels win.
2. **Macro zones** (`v2/macro_zones.py`) — draws support/resistance from the
   **preceding** session's footprint (highest wick→body = resistance,
   lowest wick→body = support). NY anchors off London, London off Asia, Asia off
   the prior NY range.
3. **Indicators** (`v2/indicators.py`) — Heikin Ashi candles, session-reset VWAP,
   EMA-12, ATR.
4. **Two-Indications entry** (`v2/strategy.py`):
   - **Indication 1 — Velocity Break:** the prior Heikin-Ashi candle closes
     beyond *both* VWAP and EMA-12, and is a *strong* candle (flat bottom for
     longs / flat top for shorts — no shadow).
   - **Indication 2 — Total Engulfing:** the current candle fully engulfs the
     prior candle's entire range (high *and* low). Enter on its close.
     ORB momentum metrics are attached if the setup fires in the first 15 min.
5. **Risk** — structural stop 1 tick past the setup swing; TP at 1:1 (Asia
   truncates) or 2:1 (London/NY expand); stop trails to breakeven at +1R then
   follows EMA-12 / local pivots; contracts auto-scale by ATR to target the
   **$500–$1,500 net-profit window** per setup.
6. **Output** — every state change emits a programmatic JSON object
   (`schema: tajari.v2.signal/1`): session, bias, entry/stop/targets, R:R,
   contracts, macro zones, ORB context, and trailing config.

### Run the V2 backtest
```bash
# All sessions
python3 scripts/v2_backtest.py --symbol MNQ --period 30d

# Full-size NQ, New York session only
python3 scripts/v2_backtest.py --symbol NQ --period 30d --session NEW_YORK
```

### Run V2 live (opt-in)
```env
# .env
STRATEGY=multi_session
SYMBOLS=["NQ","MNQ"]
```
Then start the backend as usual. V1 ORB remains the default whenever
`STRATEGY=orb`.

---

## Risk Disclaimer

This software is for educational and research purposes. Past backtest performance does not guarantee future results. Day trading involves substantial risk of loss. Prop firm evaluations can fail. Never risk money you cannot afford to lose.

---

## Architecture

```
backend/
├── main.py              FastAPI app, all API endpoints
├── config.py            Settings (all configurable via .env)
├── database.py          SQLite via SQLAlchemy
├── models/              SQLAlchemy ORM models (Trade, Signal, Account, DailyStats)
├── services/
│   ├── market_data.py   yfinance data + 25+ technical indicators
│   ├── ai_engine.py     ML model training, prediction, signal generation
│   ├── risk_manager.py  Stop loss, daily limits, prop firm rules, position sizing
│   ├── execution.py     Order submission, position monitoring, P&L tracking
│   └── scheduler.py     Async trading loop (runs every 60s during market hours)
└── brokers/
    ├── paper_broker.py  Built-in paper trading (no API keys needed)
    ├── alpaca_broker.py Alpaca Markets (stocks, ETFs, paper trading)
    └── tradovate_broker.py Tradovate (futures: MES, MNQ, MGC)
backend/strategies/
├── orb.py               V1 — validated Opening Range Breakout (DEFAULT)
├── momentum.py / ml_strategy.py
└── v2/                  V2 — multi-session engine (isolated, opt-in)
    ├── sessions.py      Asia/London/NY windows, kill zones, overlap
    ├── indicators.py    Heikin Ashi, session VWAP, EMA-12, ATR
    ├── macro_zones.py   Support/resistance from preceding session
    └── strategy.py      Two-Indications engulfing engine + JSON schema
frontend/
└── src/app/page.tsx     React dashboard with live data, P&L chart, signals panel
scripts/
├── train_model.py       Download data and train ML models
├── backtest.py          V1 ORB backtester
└── v2_backtest.py       V2 multi-session backtester
```
