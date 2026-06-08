#!/bin/bash
#
# V2 FILTER COMPARISON — does the partner's Two-Indications gate help or hurt?
# =============================================================================
# Runs the EXACT same 5 ORB configs from frequency.sh, each time WITHOUT and
# then WITH the --v2-filter flag (HA flat-candle velocity break + total-engulf).
#
# Read the output as a table:
#   • More trades  WITH v2-filter ON  = the filter isn't too restrictive
#   • Higher PF    WITH v2-filter ON  = the filter adds real edge
#   • Lower PF     WITH v2-filter ON  = the filter is cutting good trades
#   • Far fewer trades                = the filter is too tight (over-engineering)
#
# Usage:  bash scripts/v2_compare.sh
#
cd "$(dirname "$0")/.." || exit 1

KEEP="Trades taken|Total trades|Win rate|Profit factor|Total P&L|Sharpe|Max drawdown|Avg daily|V2 filter"

run() {
  label="$1"; shift
  echo ""
  echo "------------------------------------------------------------"
  echo "  $label"
  echo "------------------------------------------------------------"
  python3 scripts/backtest.py "$@" 2>&1 | grep -E "$KEEP" || echo "  (no trades)"
}

echo ""
echo "============================================================"
echo "  TAJARI — V1 ORB vs V2 OVERLAY (MNQ, 60d)"
echo "  Each config runs TWICE: V1 only | V1 + V2 two-indications"
echo "============================================================"

# ── Config 0: Baseline ──────────────────────────────────────────
echo ""
echo "============================================================"
echo "  0. BASELINE  (2/day, cutoff 12:00)"
echo "============================================================"
run "V1 only  →" \
    --symbol MNQ --period 60d --max-trades-day 2 --cutoff 12:00
run "V1 + V2  →" \
    --symbol MNQ --period 60d --max-trades-day 2 --cutoff 12:00 \
    --v2-filter

# ── Config 1: 4/day + re-entry ──────────────────────────────────
echo ""
echo "============================================================"
echo "  1. 4/day + re-entry (cutoff 12:00)"
echo "============================================================"
run "V1 only  →" \
    --symbol MNQ --period 60d --max-trades-day 4 --allow-reentry --cutoff 12:00
run "V1 + V2  →" \
    --symbol MNQ --period 60d --max-trades-day 4 --allow-reentry --cutoff 12:00 \
    --v2-filter

# ── Config 2: 6/day + re-entry ──────────────────────────────────
echo ""
echo "============================================================"
echo "  2. 6/day + re-entry (cutoff 14:00)"
echo "============================================================"
run "V1 only  →" \
    --symbol MNQ --period 60d --max-trades-day 6 --allow-reentry --cutoff 14:00
run "V1 + V2  →" \
    --symbol MNQ --period 60d --max-trades-day 6 --allow-reentry --cutoff 14:00 \
    --v2-filter

# ── Config 3: WINNER — 6/day + 5-min OR ─────────────────────────
echo ""
echo "============================================================"
echo "  3. 6/day + re-entry + 5-min OR (cutoff 14:00)  ← WINNER"
echo "============================================================"
run "V1 only  →" \
    --symbol MNQ --period 60d --max-trades-day 6 --allow-reentry \
    --cutoff 14:00 --or-minutes 5
run "V1 + V2  →" \
    --symbol MNQ --period 60d --max-trades-day 6 --allow-reentry \
    --cutoff 14:00 --or-minutes 5 \
    --v2-filter

# ── Config 4: Max frequency ──────────────────────────────────────
echo ""
echo "============================================================"
echo "  4. 10/day + re-entry + 5-min OR (cutoff 15:00)"
echo "============================================================"
run "V1 only  →" \
    --symbol MNQ --period 60d --max-trades-day 10 --allow-reentry \
    --cutoff 15:00 --or-minutes 5
run "V1 + V2  →" \
    --symbol MNQ --period 60d --max-trades-day 10 --allow-reentry \
    --cutoff 15:00 --or-minutes 5 \
    --v2-filter

echo ""
echo "============================================================"
echo "  HOW TO READ THIS:"
echo "  ▲ PF with V2 ON  = two-indications filter adds edge"
echo "  ▼ PF with V2 ON  = filter is cutting good trades"
echo "  Far fewer trades = filter too restrictive (over-engineered)"
echo "  Config 3 is the one that matters — that's your baseline."
echo "============================================================"
