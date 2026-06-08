#!/bin/bash
#
# Validation matrix for the 1R breakout baseline (PF 1.61 on MNQ).
# Confirms the edge holds across instruments and filter settings before
# we trust it with a funded account.
#
# Usage:  bash scripts/validate.sh
#
cd "$(dirname "$0")/.." || exit 1

KEEP="Signals fired|Total trades|Win rate|Profit factor|Total P&L|Sharpe|Max drawdown|Avg daily|Return"

run() {
  label="$1"; shift
  echo ""
  echo "============================================================"
  echo "  $label"
  echo "============================================================"
  python3 scripts/backtest.py "$@" 2>&1 | grep -E "$KEEP" || echo "  (no trades / see full output)"
}

echo ""
echo "TAJARI — 1R BREAKOUT VALIDATION MATRIX"
echo "Looking for: edge holds on MES too, and filters don't break it."

# 1. The winner, re-confirmed
run "MNQ baseline — 1R, filters OFF (the winner)" \
    --symbol MNQ --strategy orb --period 60d --entry-mode breakout --no-trend --target-r 1.0

# 2. Same recipe on MES — does the edge generalize?
run "MES cross-check — 1R, filters OFF" \
    --symbol MES --strategy orb --period 60d --entry-mode breakout --no-trend --target-r 1.0

# 3. MNQ with the FULL filter stack on (trend + news) — sharper or worse?
run "MNQ — 1R, trend + news filters ON" \
    --symbol MNQ --strategy orb --period 60d --entry-mode breakout --target-r 1.0

# 4. MES with the full filter stack on
run "MES — 1R, trend + news filters ON" \
    --symbol MES --strategy orb --period 60d --entry-mode breakout --target-r 1.0

echo ""
echo "============================================================"
echo "  DONE. Compare win rate + profit factor across the four."
echo "  We want PF > 1.2 on BOTH instruments to call it robust."
echo "============================================================"
