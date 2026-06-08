#!/bin/bash
#
# FREQUENCY EXPERIMENT
# ===================
# The validated 1R breakout edge only fired ~14 trades in 57 days because of
# the "one trade per side per day" + short entry window. This sweep loosens
# those constraints to see how many MORE trades we can take while KEEPING
# profit factor above ~1.2. More trades at the same edge = more daily dollars,
# with no extra per-trade risk.
#
# Trades never overlap (one position at a time), so this is realistic.
#
# Usage:  bash scripts/frequency.sh
#
cd "$(dirname "$0")/.." || exit 1

KEEP="Total trades|Win rate|Profit factor|Total P&L|Sharpe|Max drawdown|Avg daily"

run() {
  label="$1"; shift
  echo ""
  echo "============================================================"
  echo "  $label"
  echo "============================================================"
  python3 scripts/backtest.py "$@" 2>&1 | grep -E "$KEEP" || echo "  (no trades)"
}

echo ""
echo "TAJARI — FREQUENCY SWEEP (MNQ, 60d, validated 1R breakout)"
echo "Goal: more trades, profit factor stays > 1.2"

# 0. Baseline — the validated winner (2 trades/day cap, noon cutoff)
run "0. BASELINE  (2/day, cutoff 12:00)" \
    --symbol MNQ --period 60d --max-trades-day 2 --cutoff 12:00

# 1. More trades/day, allow re-entry
run "1. 4/day + re-entry (cutoff 12:00)" \
    --symbol MNQ --period 60d --max-trades-day 4 --allow-reentry --cutoff 12:00

# 2. More trades + longer entry window
run "2. 6/day + re-entry (cutoff 14:00)" \
    --symbol MNQ --period 60d --max-trades-day 6 --allow-reentry --cutoff 14:00

# 3. Shorter opening range (5 min) = earlier, more breakouts
run "3. 6/day + re-entry + 5-min OR (cutoff 14:00)" \
    --symbol MNQ --period 60d --max-trades-day 6 --allow-reentry --cutoff 14:00 --or-minutes 5

# 4. Max frequency — wide open
run "4. 10/day + re-entry + 5-min OR (cutoff 15:00)" \
    --symbol MNQ --period 60d --max-trades-day 10 --allow-reentry --cutoff 15:00 --or-minutes 5

echo ""
echo "============================================================"
echo "  Pick the row with the MOST trades that still has PF > 1.2"
echo "  and a healthy 'Avg daily P&L'. That's our scaled baseline."
echo "============================================================"
