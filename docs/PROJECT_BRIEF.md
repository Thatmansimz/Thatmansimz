# Tajari AI Trading — Project Brief

> Hand this document to any AI assistant or collaborator who needs full context
> on what this platform is, how it works, and where it stands today.

## What this is

Tajari AI Trading is a **self-hosted, automated futures day-trading platform**
built by Michael. It scans micro E-mini futures (MES = Micro S&P 500, MNQ =
Micro Nasdaq-100), generates rule-based trade signals, sizes positions by risk,
and executes them through a broker abstraction — currently a **paper broker**
(simulated fills at real market prices, no real money). It has a live web
dashboard showing engine state, signals, open positions, P&L, and performance
analytics.

**Current stage: Stage 2 — live paper trading.** The engine takes real-time
paper trades using actual market prices. No real capital is at risk yet. The
goal is to prove out the strategies with a live forward test before connecting
a funded/prop-firm account.

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy + SQLite (`data/trading.db`) |
| Market data | yfinance (Yahoo Finance futures quotes, 5-min bars) |
| Frontend | Next.js 14, Tailwind CSS, Recharts |
| Scheduler | asyncio loop inside the FastAPI app (scans every cycle, tracks scan status) |
| Config | `.env` file (strategy, symbols, risk limits, news filter, prop-firm rules) |

Run it locally:

```bash
# backend
python3 -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
# frontend
cd frontend && npm run dev
```

## Repository map

```
backend/
  main.py                  FastAPI app + /api/status (engine state, ORB window, scan activity)
  services/
    scheduler.py           trading loop: scan → signal → risk check → execute
    execution.py           order placement, P&L bookkeeping (per-symbol point values)
    risk_manager.py        position sizing, signal validation, POINT_VALUES table
    market_data.py         yfinance wrapper (latest price + historical bars)
  brokers/
    paper_broker.py        simulated broker — fills/exits at REAL market prices
  strategies/
    orb.py (V1)            Opening Range Breakout — the validated NY-session strategy
    v2/                    Multi-session Heikin-Ashi engine (Asia/London/NY)
      strategy.py          two-indications entry logic + Asia tuning dials
      sessions.py          session windows, kill zones, overlap, volatility pause
      macro_zones.py       prior-session support/resistance zones
      indicators.py        Heikin Ashi, session VWAP, EMA-12, ATR
scripts/
  backtest.py              V1 ORB backtester
  v2_backtest.py           V2 multi-session backtester (Asia tuning flags)
frontend/src/app/page.tsx  the entire dashboard (single-page)
data/
  trading.db               SQLite: trades, signals, account history
  news_calendar.json       red-folder news events (currently placeholder — needs real data)
```

## The two strategies

### V1 — ORB (Opening Range Breakout) — `STRATEGY=orb`

The validated workhorse. NY session only.

- Opening range = first **5 minutes** after 9:30 AM ET open.
- Trades breakouts of that range, **9:35 AM – 2:00 PM ET** entry window only.
- Max 6 trades/day, re-entry allowed, red-folder news filter ON.
- This exact config ("Config 3") was selected by grid search in backtesting.
- Symbols: MES + MNQ.

### V2 — Multi-Session Engine — `STRATEGY=multi_session`

A 24/5 strategy trading three global sessions, built from a business-partner
spec. Entry requires **two indications**:

1. **Indication 1 (bias)**: a strong Heikin-Ashi candle (flat bottom for longs
   / flat top for shorts) closing on the right side of both session VWAP and
   EMA-12.
2. **Indication 2 (trigger)**: the next real candle **totally engulfs** the
   prior bar's range and closes in the bias direction.

Risk model: structural stop behind the engulfing swing ± 1 tick, targets at
1R and a session R:R cap (2R for London/NY), breakeven at +1R, then an EMA-12
trailing stop. Contracts are sized so the 2R target lands in a **$500–$1,500
profit window**, scaled down by ATR in volatile NY conditions.

Sessions and kill zones (all ET):

| Session | Window | Kill zone (peak volatility) |
|---|---|---|
| Asia | 8 PM – 4 AM | **8–10 PM only** (hard gate — see below) |
| London | 3 AM – 11:30 AM | 4–6 AM |
| New York | 9:30 AM – 4 PM | 9:30–11:30 AM |

**Asia tuning (grid-searched, critical):** Asia traded all night lost -$878
over 30 days. Three dials fixed it, now defaults in `v2/strategy.py`:

- `asia_kill_zone_only = True` — only enter 8–10 PM ET
- `asia_max_rr = 2.0` — 2R target (1.5R lost -$1,430; 2.0R is the only positive config)
- `asia_require_macro_zone = False` — the macro S/R filter forced entries AT
  resistance/support (the worst spot for a breakout) and was removed

## Validated backtest results (30 days, MNQ, 5-min bars)

**V2 all sessions combined:** 68 trades · 41.2% win rate · **profit factor 1.34**
· **+$5,127** total.

By session: NY +$4,950 · London +$149 · Asia +$27 (Asia: 11 trades, 36.4% WR,
PF 1.01 — barely positive but no longer a bleed; the 1.91× payoff ratio means
it only needs ~34% WR to break even).

The win rate is ~41% by design — this is a **trend/breakout system** that
takes small structural-stop losses and lets 2R winners pay for them. Judge it
by profit factor and expectancy, not win rate.

## Hard-won bugs already found and fixed (do not reintroduce)

1. **Paper broker random-walk exits** — exits used to be decided by a biased
   random number instead of the market. Now `paper_broker.py` pulls real
   prices from `MarketDataService` and fills exits exactly at the stop/target
   level. Paper P&L is now truthful.
2. **Per-symbol point values** — P&L math was hardcoded to $5/point (MES).
   MNQ is $2/point, so MNQ P&L was inflated 2.5×. Everything now uses the
   `POINT_VALUES` dict in `risk_manager.py` (MES 5, MNQ 2, NQ 20, ES 50, …).
3. **Silent confidence-gate blocking** — the 0.65 `AI_CONFIDENCE_THRESHOLD`
   (meant for an ML strategy) was silently blocking valid ORB signals scoring
   0.55–0.62. The backtest never had that gate, so live was stricter than
   what was validated → 0 trades all session. `risk_manager.validate_signal()`
   now skips the confidence check for rule-based strategies (`orb`,
   `momentum`).
4. **Backtest CLI defaults drifting from validated config** — `v2_backtest.py`
   flags/defaults must always match the strategy's validated defaults
   (kill-zone-only=True, rr=2.0, macro=False). This drifted once and produced
   confusing results; it's fixed, but check it whenever the strategy is tuned.
5. **Equity-clock kill switch** — the risk manager's "minutes until close"
   used the 4 PM ET stock close, so after 3:55 PM ET all trading was blocked
   and any open position was force-closed as "end_of_day". Invisible for the
   NY-only ORB strategy, fatal for V2's overnight sessions. multi_session now
   uses the futures clock (5 PM ET daily halt).
6. **In-memory paper account** — balance and open positions used to live in
   process memory; any restart silently reset the account to $50k and
   orphaned open trades. Now persisted to `data/paper_state.json`, and
   `Account.balance` moves on every trade close.

## Dashboard concepts (frontend/src/app/page.tsx)

- **Engine state pill** (header): `DISARMED` (trading off) → `ARMED · OPENS IN
  Xh Ym` (on, waiting for window) → `LIVE` (in window, scanning) → `ARMED ·
  DONE FOR TODAY` (after the 2 PM ET ORB cutoff). "AI ACTIVE" ≠ trading —
  trading only happens when `TRADING_ENABLED=true` AND the strategy's window
  is open.
- **Scan activity** (AI Signals panel): live scan status — SCANNING, SIGNAL
  SEEN, TRADE TAKEN, NO SETUP YET — plus cycle count and last-scan time, so
  "0 trades" is never a mystery again.
- **Session bar**: shows Asia/London/NY market hours (futures trade 24/5).
  A session being "open" does not mean the engine trades it — V1 only trades
  the NY ORB window; V2 trades only kill zones.
- **Trade Insights → By Instrument**: MES vs MNQ head-to-head (expectancy
  $/trade, P&L bar, payoff ratio, "LEADING" crown).

## Key .env settings

```
BROKER=paper
TRADING_ENABLED=true          # Stage 2 switch (also toggleable from dashboard)
STRATEGY=multi_session        # "orb" (V1) or "multi_session" (V2)
SYMBOLS=["MNQ"]               # V1 uses ["MES","MNQ"]; V2 recommended ["MNQ"]
AI_CONFIDENCE_THRESHOLD=0.65  # only applies to ML strategies now
MAX_STOP_LOSS_DOLLARS=250
DAILY_PROFIT_TARGET_DOLLARS=1000
NEWS_FILTER_ENABLED=true
```

## The 60-day forward-test campaign (current mission)

The project's verdict was accepted: the backtest is directional evidence, not
proof. The mission now is a **60-day untouched live paper forward test** with
an audited track record. Everything below was built for it:

- **Friction is modeled everywhere**: $1.50/side/contract commission and
  1-tick adverse slippage on entries + stop exits (`COMMISSION_PER_SIDE`,
  `SLIPPAGE_TICKS` in config, shared logic in `backend/services/costs.py`).
  Applies to live paper fills AND both backtesters, so they stay comparable.
- **Restart-proof state**: paper balance + open positions persist to
  `data/paper_state.json`; the campaign start date to
  `data/forward_test.json`; daily equity + uptime heartbeat to the
  `equity_snapshots` table. A restart never wipes the record.
- **Campaign tracker**: auto-starts the first time the engine boots armed.
  `GET /api/forward-test/status` → day X/60, equity curve, uptime, trade
  record. The dashboard shows a FORWARD TEST card with a progress bar.
- **Supervised runtime**: `scripts/run_engine.sh` (auto-restart + caffeinate,
  no --reload) and `deploy/com.tajari.engine.plist` (launchd service).
  Full runbook: **docs/FORWARD_TEST.md** — read it before touching anything.
- **Futures clock fix**: the risk manager previously used the 4 PM ET equity
  close, which blocked ALL trading after 3:55 PM and instantly force-closed
  overnight positions — fatal for V2's Asia kill zone. multi_session now runs
  on the futures clock (daily 5 PM ET halt).

**The rules while it runs**: no strategy tweaks, no resets, no "small
improvements" — any logic change restarts the track record. Judge the result
at day 60 by profit factor / expectancy / max drawdown, not win rate. If it
survives, the path to capital is a prop-firm eval (~$50–150, Apex/TraderFi
allow automation; TopStep does not), budgeted as 2–3 attempts. No selling
signals/access before a long audited record (CTA/NFA territory).

## Other pending items

- Populate `data/news_calendar.json` with real ForexFactory red-folder events.
- The Asia edge (+$27 on 11 trades) is statistical noise until the live
  sample grows — the forward test is what settles it.
- **Branch**: all work lives on `claude/ai-day-trading-platform-E61dn`.
