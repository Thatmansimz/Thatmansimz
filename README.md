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
# Open http://localhost:3000
```

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
frontend/
└── src/app/page.tsx     React dashboard with live data, P&L chart, signals panel
scripts/
├── train_model.py       Download data and train ML models
└── backtest.py          Simulate strategy on historical data
```
