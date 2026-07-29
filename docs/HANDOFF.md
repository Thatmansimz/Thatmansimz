# Tajari AI Trading — Handoff & Context Document

> **Purpose:** hand this to a new Claude Code session, a business partner, or
> your future self and be fully caught up in ten minutes.
> **Last updated:** 2026-07-29 (Day 2 of the 60-day forward test)
> **Repo:** `Thatmansimz/Thatmansimz` · branch `claude/ai-day-trading-platform-E61dn`
> (note: this branch IS the main line — the repo has no `main` branch, which is
> why GitHub's "Create PR" button fails. Nothing is broken; there is simply
> nothing to merge into.)

---

## 1. What this is, in one paragraph

Tajari is a self-hosted automated futures day-trading platform. It scans micro
E-mini Nasdaq futures (MNQ), generates rule-based signals, sizes positions by
dollar risk, executes through a broker abstraction, and records every trade to
an auditable database. It currently runs in **paper mode** — simulated fills at
real market prices, honest commission and slippage, **no real money at risk**.
A Next.js dashboard shows engine state, live scan activity, open positions,
and performance analytics. It runs 24/5 on a MacBook Air under `launchd`, with
a watchdog that pushes phone alerts if it stops.

**The mission right now:** run an untouched 60-day live paper forward test to
produce an *audited track record*, then use that record to decide whether to
pursue real capital via a prop-firm evaluation.

---

## 2. Current status (as of Day 2)

| | |
|---|---|
| Campaign | Day 2 of 60, started 2026-07-28 |
| Trades | 3 closed · 2W / 1L |
| P&L | **+$1,236.00** |
| Strategy | V2 `multi_session` |
| Symbol | MNQ only |
| Broker | `paper` |
| Account | $50,000 simulated |
| Engine | Running under launchd, feed healthy |

**Read this number correctly:** the backtest baseline averages ~$171/day.
Three trades is an anecdote, not evidence — one winner (+$932.50) is more than
the entire net. The strategy is designed to win ~41% of the time, so losing
streaks of 4–5 are *expected*, not malfunctions. Judge nothing before ~40 trades.

**Footnote on record purity:** trades 39, 40, 41 were taken *before* the
"parity" fixes landed (see §5). They are honestly recorded but came from a
slightly different exit/sizing system. At Day 60, report the record two ways:
full campaign, and parity-clean (everything after 2026-07-29 ~15:00 UTC).

---

## 3. The two strategies

### V1 — ORB (`STRATEGY=orb`)
Opening Range Breakout. Trades breakouts of the first 5 minutes after the 9:30
ET NY open, entries only 9:35–14:00 ET. Max 6 trades/day, re-entry allowed,
news filter on. This was the original validated strategy. **Not currently running.**

### V2 — Multi-Session (`STRATEGY=multi_session`) ← ACTIVE
A 24/5 engine trading three global sessions. Entry requires **two indications**:

1. **Indication 1 (bias):** a strong Heikin-Ashi candle (flat bottom for longs,
   flat top for shorts) closing on the correct side of both session VWAP and EMA-12.
2. **Indication 2 (trigger):** the next real candle *totally engulfs* the prior
   bar's range and closes in the bias direction.

Risk model: structural stop behind the engulfing swing ±1 tick; target at the
session R:R cap (2R); breakeven at +1R; then an EMA-12 trailing ratchet.
Contracts sized so the 2R target lands in a **$500–1,500 profit window**.

**Sessions (all ET):**

| Session | Window | Kill zone (where it hunts) |
|---|---|---|
| Asia | 8 PM – 4 AM | **8–10 PM only** (hard gate) |
| London | 3 AM – 11:30 AM | 4–6 AM |
| New York | 9:30 AM – 4 PM | 9:30–11:30 AM |

**Validated backtest (30d, MNQ):** 68 trades · 41.2% WR · PF 1.34 · **+$5,127**.
⚠️ This baseline needs regenerating — the Asia sizing fix (§5) changed the
strategy. Run: `python3 scripts/v2_backtest.py --symbol MNQ --period 30d`

---

## 4. Architecture

```
backend/
  main.py                    FastAPI app, all endpoints, lifespan/startup
  config.py                  Settings (env-driven), prop-firm rule tables
  database.py                SQLAlchemy engine + additive sqlite migrations
  models/
    trade.py                 Trade, DailyStats, EquitySnapshot
    signal.py, account.py
  services/
    scheduler.py             The 60s trading loop
    execution.py             Trade lifecycle, P&L, risk gates, trailing
    risk_manager.py          Market clock, sizing, validation, POINT_VALUES
    market_data.py           yfinance wrapper + feed health + self-heal
    costs.py                 Commission + slippage model
    forward_test.py          60-day campaign tracker
  brokers/
    paper_broker.py          ACTIVE — simulated fills at real prices
    tradovate_broker.py      ⚠️ NOT READY (see §7)
    alpaca_broker.py         ⚠️ WRONG ASSET CLASS — Alpaca has no futures
  strategies/
    orb.py                   V1
    v2/                      V2 (FROZEN during campaign)
      strategy.py, sessions.py, macro_zones.py, indicators.py
scripts/
  backtest.py                V1 backtester
  v2_backtest.py             V2 backtester ← the baseline generator
  run_engine.sh              Supervised launcher (auto-restart, caffeinate)
  watchdog.sh                5-min health check + phone alerts
deploy/
  com.tajari.engine.plist    launchd service (engine)
  com.tajari.watchdog.plist  launchd service (watchdog)
frontend/src/app/page.tsx    The entire dashboard
data/
  trading.db                 ← THE RECORD. SQLite. Trades, signals, stats.
  paper_state.json           Broker balance + open positions (survives restart)
  forward_test.json          Campaign start date (immovable)
```

**Tech:** Python · FastAPI · SQLAlchemy/SQLite · yfinance · Next.js 14 ·
Tailwind · Recharts.

---

## 5. Bug lore — read this before changing anything

This project's defining characteristic is that **it looked healthy while being
completely broken, three separate times.** Every bug below was found by
adversarial audit and verified by reproduction. Do not reintroduce them.

### The silent killers (all fixed)

1. **25 days of zero trades — blind engine.** yfinance's auth cookie went stale;
   every download returned empty forever. The dashboard said "scanning." Fixed
   with a feed-health tracker, a self-heal that deletes the cached cookie row
   (verified against yfinance 1.5.2 internals — the first version of this fix
   was a no-op targeting APIs that don't exist), and loud alerts.
2. **V2 could never trade — four stacked blockers.** (a) V1's $250 risk cap
   rejected 100% of V2 signals; (b) the ML confidence gate rejected V2 setups
   outside kill zones; (c) `execution.py` hard-subscripted three fields V2 never
   emits → `KeyError` on every signal, logged as one quiet INFO line; (d) the
   futures calendar was shifted one weekday, blocking every Sunday Asia session.
3. **Live ≠ backtest — the campaign was measuring a different system.**
   - Live exited at **1R** while the backtest exits at **2R** (winners halved).
   - Live evaluated the **still-forming candle**, so stops were measured from a
     moving low → positions up to 4× oversized.
   - Live sampled one price/minute and **couldn't see wicks**, so it survived
     stop-outs the backtest books as full losses (~$590 divergence on one bar).
   - Live trailed to breakeven at **0.5R** with no EMA ratchet; the backtest
     uses 1R + EMA-12. This manufactured trade 40's −$70 scratch.
   - Asia positions were **2× oversized** — the strategy's target used
     `asia_max_rr=2.0` while its sizing used `session.max_rr=1.0`.
4. **Exits decided by a random number generator.** The price feed used for
   stop/target checks added ±0.05% simulated jitter (±10 MNQ points — wider
   than a typical stop). Wins and losses were coin flips.
5. **No `rollback()` anywhere in the codebase.** One failed DB write poisons
   the long-lived session permanently; the engine stops trading *and* stops
   monitoring open positions while every health signal stays green.
6. **Phantom five-figure losses.** `close_position` returned `{"price": 0.0}`
   when it had nothing to close, and that 0.0 was booked as a real exit price —
   which also permanently tripped the max-drawdown lockout.
7. **Analytics mixed strategies.** The insights panel analyzed *every trade
   ever*, blending June's V1 ORB replay into the live V2 record — producing
   confident false advice like "drop MES" for an instrument not being traded.

### Standing rules learned the hard way

- **Zero trades is not proof of a quiet market.** Check `rejections` on
  `/api/status`. Tripwire: **3 trading days with 0 trades AND 0 rejections → investigate.**
- **A running engine can be blind.** Health = feed healthy + scan fresh + DB alive.
- **Any silent failure mode must become loud** before it's considered fixed.
- **The strategy is frozen during the campaign.** Bug fixes yes, tuning no.

---

## 6. Operating the system

```bash
# Start (launchd — survives reboot & logout; auto-restarts on crash)
launchctl load ~/Library/LaunchAgents/com.tajari.engine.plist
launchctl load ~/Library/LaunchAgents/com.tajari.watchdog.plist

# Dashboard (manual, optional — engine runs without it)
cd ~/Thatmansimz/frontend && npm run dev     # localhost:3000 or :3001

# Health check
curl -s http://localhost:8000/api/status | python3 -m json.tool
curl -s http://localhost:8000/api/forward-test/status | python3 -m json.tool

# The record
sqlite3 -header -column data/trading.db \
  "select id,symbol,side,qty,entry_price,exit_price,status,exit_reason,
   round(net_pnl,2) net, r_multiple R, session, entry_time
   from trades where entry_time >= '2026-07-28' order by id;"
```

**Config lives in `.env`** (not committed). Key values:
`BROKER=paper`, `TRADING_ENABLED=true`, `STRATEGY=multi_session`,
`SYMBOLS=["MNQ"]`, `COMMISSION_PER_SIDE=1.50`, `SLIPPAGE_TICKS=1`,
`V2_MAX_RISK_DOLLARS=1100`, `NTFY_TOPIC=<secret>` (phone alerts via the ntfy app).

**Physical requirements:** Mac plugged in, lid open, logged in, auto-updates off.

---

## 7. The path to real money (researched 2026-07-29)

**Tradovate is NOT a route into a prop firm.** Tradovate grants API access only
to live funded brokerage accounts with $1,000+ *plus* a paid API add-on
(~$25/mo). Prop-firm and evaluation accounts are explicitly ineligible.

**TopstepX is currently the strongest candidate.** Topstep launched its own API
in late April 2026 and permits automation in **both** the evaluation (Trading
Combine) and funded accounts, ~$29/mo. Critical constraint: **all trading must
originate from a personal device — VPS/VPN/remote servers are prohibited.**
(This engine already runs on the Mac, so it complies — and can never move to
the cloud.)

Other reportedly algo-friendly firms: Take Profit Trader, Elite Trader Funding,
My Funded Futures. **Verify terms the week you buy** — these policies changed
twice in the six months before this was written.

**Before any live broker, three code blockers must be fixed** (documented in
`tradovate_broker.py`, and the same gaps will apply to any new broker class):
1. `get_last_fill()` unimplemented → trades would hang open forever, then the
   one-position guard blocks all future signals.
2. `update_stop()` unimplemented → the trailing stop never reaches the exchange.
3. Contract symbols need expiry codes (`MNQU6`), not the bare root (`MNQ`).

⚠️ Not financial advice. Most people fail evaluations. Budget 2–3 attempts and
treat it as a bet, not income. Selling signals/access before a long audited
track record raises CTA/NFA registration questions.

---

## 8. What's missing for enterprise-grade

Ranked by what would actually hurt:

1. **No automated tests.** Everything verified so far was ad-hoc scripts written
   during audits. A regression suite covering the trade lifecycle, P&L math,
   session clocks, and the ten parity rules is the single highest-value addition.
2. **The record has no backup.** `data/trading.db` is one file on one laptop.
   Losing it loses the campaign. Needs a nightly encrypted snapshot off-machine.
3. **No automated reconciliation.** Nothing cross-foots trades vs DailyStats vs
   equity snapshots vs account balance. Every audit found a mismatch class.
4. **No CI.** Nothing verifies a push doesn't break the engine before it's pulled
   onto the trading machine.
5. **Config drift.** `.env` is hand-edited and unversioned; two separate outages
   traced back to it. Needs a validated startup check that refuses to boot on a
   nonsensical combination.
6. **Observability is grep.** Logs are plain text. No metrics, no structured
   events, no history of engine state over time.
7. **Alerting is binary.** Up/down only. No alert on "unusual drawdown,"
   "trade opened," or "no signals in 48h."
8. **Secrets in plaintext `.env`** — acceptable for paper, not for live API keys.

---

## 9. Open decisions

- **Risk per trade.** V2 risks $400–1,100 per trade on $50k (1–2%). That's what
  the backtest sized, so it's what we forward-test. On a funded account with a
  $2,000 daily limit, two losers ends the day. Revisit before real money.
- **Which prop firm**, and when to buy the eval.
- **Whether to keep the profit-target cap.** Currently disabled for V2 (it
  censored the winning tail); V1 keeps it.
- **Deploying the dashboard publicly** — needs auth first; nobody should be able
  to hit `/api/trading/stop` from the internet.

---

## 10. If you are a new Claude Code session

Start here: read this file, then `docs/FORWARD_TEST.md` (the operating runbook)
and `docs/PROJECT_BRIEF.md`. Then run the health check in §6.

**The prime directive: the strategy in `backend/strategies/` is frozen.** Fix
bugs, never tune. Every change that alters trading behaviour restarts the
credibility of the record.

**The second directive: assume silent failure.** This system has looked healthy
while completely broken three times. When something seems fine, prove it with a
query or a reproduction, not a glance.
