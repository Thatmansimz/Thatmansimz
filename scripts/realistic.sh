#!/bin/bash
#
# REALISTIC SIZED P&L
# ===================
# Validated Config 3 (5-min OR, 14:00 cutoff), sized to use the full $250
# risk budget per trade (your tight-stop rule, fully respected). Runs MNQ
# and MES — a single funded account would trade both.
#
# Usage:  bash scripts/realistic.sh
#
cd "$(dirname "$0")/.." || exit 1

KEEP="Trades taken|Total trades|Win rate|Profit factor|Total P&L|Sharpe|Max drawdown|Avg daily"

run() {
  label="$1"; shift
  echo ""
  echo "============================================================"
  echo "  $label"
  echo "============================================================"
  python3 scripts/backtest.py "$@" 2>&1 | grep -E "$KEEP" || echo "  (no trades)"
}

echo ""
echo "TAJARI — REALISTIC SIZED P&L (Config 3, full \$250 risk budget)"

run "MNQ — sized to \$250 budget" \
    --symbol MNQ --period 60d --max-trades-day 6 --allow-reentry \
    --cutoff 14:00 --or-minutes 5 --size-to-budget

run "MES — sized to \$250 budget" \
    --symbol MES --period 60d --max-trades-day 6 --allow-reentry \
    --cutoff 14:00 --or-minutes 5 --size-to-budget

echo ""
echo "============================================================"
echo "  Add the two 'Avg daily P&L' numbers — that's roughly what"
echo "  ONE funded account trading both micros would make per day,"
echo "  while never risking more than \$250 on any single trade."
echo "============================================================"
