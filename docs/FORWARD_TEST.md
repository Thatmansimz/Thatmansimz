# The 60-Day Forward Test — Runbook

This is the playbook for the live paper campaign: how to start it, how to
keep it running for 60 days straight, and — most importantly — what NOT to
touch while it runs. The goal is an **audited track record**: an immovable
start date, a daily equity snapshot, and an uptime heartbeat that makes any
gap visible instead of quietly forgotten.

## Why this matters

The 30-day backtest (PF 1.34, +$5,127 on MNQ) is *directional evidence*, not
proof. 68 trades is a small sample, the Asia edge (+$27 on 11 trades) is
statistical noise, and one month says nothing about regime changes. The
forward test is the proof: 60–90 days of live paper trades, with commission
($1.50/side) and 1-tick slippage baked into every fill, untouched.

If it survives that, the path to real capital is a **prop-firm evaluation**
(~$50–150), not your own account. Budget for 2–3 attempts and treat it as a
bet. Do not sell signals or access before there's a long audited record —
that's CTA/NFA registration territory.

## One-time setup (5 minutes)

1. **Configure `.env`** (in the repo root):

   ```
   BROKER=paper
   TRADING_ENABLED=true
   STRATEGY=multi_session      # or "orb" for the V1 NY-only strategy
   SYMBOLS=["MNQ"]
   ```

2. **Keep the Mac awake.** A sleeping laptop is the #1 killer of long paper
   tests. Either:
   - System Settings → Displays → Advanced → "Prevent automatic sleeping on
     power adapter when the display is off" (and keep it plugged in), or
   - rely on the launcher script — it wraps the engine in `caffeinate`.

3. **Start the engine — pick ONE:**

   **Option A — supervised script** (simplest; terminal must stay open, or
   use `nohup`):
   ```bash
   ./scripts/run_engine.sh
   # or, to survive closing the terminal:
   nohup ./scripts/run_engine.sh > /dev/null 2>&1 &
   ```

   **Option B — launchd service** (best: survives logout AND reboot):
   ```bash
   # 1. Edit deploy/com.tajari.engine.plist — replace REPO_PATH with the
   #    absolute path to this repo (e.g. /Users/you/Thatmansimz), 4 spots.
   # 2. Install:
   cp deploy/com.tajari.engine.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.tajari.engine.plist
   # Check it's alive:
   launchctl list | grep tajari
   ```

   ⚠️ **Never use `--reload` for the campaign.** It's a dev flag that
   restarts the process on every file save. The launcher script already
   omits it.

4. **That's it.** The moment the engine boots with `TRADING_ENABLED=true`,
   the 60-day campaign auto-starts: `data/forward_test.json` records the
   start date, and the dashboard shows a **FORWARD TEST · DAY X/60** card
   with the equity curve and today's uptime.

## What survives a crash or restart (by design)

| Thing | Where it lives | Restart-safe? |
|---|---|---|
| Paper balance + open positions | `data/paper_state.json` | ✅ |
| Trades, signals, daily stats | `data/trading.db` (SQLite) | ✅ |
| Campaign start date | `data/forward_test.json` | ✅ |
| Daily equity snapshots + uptime | `equity_snapshots` table | ✅ |
| The engine process itself | run_engine.sh / launchd restarts it | ✅ |

## Watchdog + phone alerts (strongly recommended)

`scripts/watchdog.sh` checks the engine every 5 minutes — API up, scheduler
running, last scan fresh. If the engine stops recording it fires a macOS
notification, and (if configured) a **push notification to your phone**:

1. Install the free **ntfy** app (iOS/Android), no account needed.
2. In the app, subscribe to a topic nobody would guess, e.g.
   `tajari-mike-x7k2q`.
3. Add that topic to `.env`:
   ```
   NTFY_TOPIC=tajari-mike-x7k2q
   ```
4. Install both launchd jobs (engine + watchdog) — replace REPO_PATH first
   or use the sed one-liner:
   ```bash
   sed "s|REPO_PATH|$HOME/Thatmansimz|g" deploy/com.tajari.engine.plist   > ~/Library/LaunchAgents/com.tajari.engine.plist
   sed "s|REPO_PATH|$HOME/Thatmansimz|g" deploy/com.tajari.watchdog.plist > ~/Library/LaunchAgents/com.tajari.watchdog.plist
   launchctl load ~/Library/LaunchAgents/com.tajari.engine.plist
   launchctl load ~/Library/LaunchAgents/com.tajari.watchdog.plist
   ```

Alert policy: first alert after ~10 minutes down (so the supervisor's own
quick restarts don't spam you), reminders every ~30 minutes while down, one
"RECOVERED" note when it's back. Test it anytime:
`bash scripts/watchdog.sh` (should print nothing and exit clean when healthy).

## Protect-the-60-days checklist (Mac settings)

- **Power**: keep the Mac plugged in, lid open. The engine wraps itself in
  `caffeinate` so the system won't sleep while it runs (display sleep is fine).
- **Updates**: System Settings → General → Software Update → ⓘ → turn OFF
  "Install macOS updates automatically" (surprise reboots are the enemy;
  install updates manually at a time you choose — launchd restarts the
  engine after any reboot once you log in).
- **After any reboot**: just log in. launchd starts the engine + watchdog
  automatically at login.
- **Guard rails in code**: while the campaign is active, the replay/reset
  endpoints refuse to touch the trades table (HTTP 409) unless called with
  `?force=true` — so a stray click can't erase the record.

## The rules while it runs

1. **Don't touch the strategy.** No parameter tweaks, no "small improvements".
   The moment you change the logic, the track record restarts from zero.
   Collect ideas in a notes file and batch them for after day 60.
2. **Don't reset anything.** `data/paper_state.json`, `data/forward_test.json`,
   and `data/trading.db` ARE the track record.
3. **Checking in is fine.** Open the dashboard whenever you want. Look, don't
   touch. The uptime % on the Forward Test card tells you if the engine had
   gaps today.
4. **If the engine dies**, the supervisor restarts it automatically. If the
   whole machine was off for a day, that's OK — the missing snapshot day is
   visible, which is exactly what "audited" means. Just get it running again.
5. **Git pulls are allowed only for fixes that keep it running** (crash
   fixes, data-feed fixes) — never for strategy changes.

## Daily/weekly check-in (2 minutes)

- Dashboard → Forward Test card: day counter advancing? uptime green?
- `tail -50 logs/engine-$(date +%Y-%m-%d).log` — any repeated errors?
- That's all. Resist the urge to do more.

## After day 60

- Export the record: trades table + equity_snapshots + the dashboard insights.
- Judge by **profit factor, expectancy, and max drawdown** — not win rate
  (this is a breakout system; ~40% WR with 2R winners is by design).
- If PF ≥ ~1.2 net of friction over 60+ days across regimes → consider a
  prop-firm eval (Apex/TraderFi allow automation; TopStep does NOT).
- If it bleeds → the system told you the truth for free. Iterate and rerun.

## Costs modeled (so nobody forgets)

- Commission: `$1.50/side/contract` → $3.00 round trip (`COMMISSION_PER_SIDE`)
- Slippage: 1 tick against you on entries and stop exits; targets fill at
  price (`SLIPPAGE_TICKS`)
- Both apply to live paper fills AND both backtesters, so live results and
  backtests stay comparable.
