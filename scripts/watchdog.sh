#!/usr/bin/env bash
#
# Tajari engine watchdog — runs every 5 minutes via launchd.
#
# Checks three levels of health, not just "is the port open":
#   1. API responds on localhost
#   2. the trading scheduler is actually running
#   3. the last scan cycle is fresh (< 5 minutes old)
#
# On failure it fires a macOS notification, and — if NTFY_TOPIC is set in
# .env — a push notification to your phone via ntfy.sh (free, no account:
# install the ntfy app, subscribe to your topic, done).
#
# Alerting policy: first alert after 2 consecutive bad checks (~10 min down,
# avoids false alarms during the supervisor's own restarts), then a reminder
# every ~30 minutes while down, and one "RECOVERED" note when it comes back.

set -u
cd "$(dirname "$0")/.."

PORT="${API_PORT:-8000}"
STATE="/tmp/tajari_watchdog.state"

# Optional phone push: add  NTFY_TOPIC=your-secret-topic  to .env
NTFY_TOPIC="$(grep -E '^NTFY_TOPIC=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d ' ')"

check() {
  python3 - "$PORT" <<'PY'
import json, sys, urllib.request
from datetime import datetime

port = sys.argv[1]
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=10) as r:
        s = json.load(r)
except Exception as e:
    print(f"API unreachable ({e.__class__.__name__})"); sys.exit(1)

if not s.get("scheduler_running"):
    print("scheduler not running"); sys.exit(1)

lc = s.get("last_cycle")
if lc:
    try:
        t = datetime.fromisoformat(lc)
        age = (datetime.now(t.tzinfo) - t).total_seconds()
        if age > 300:
            print(f"last scan cycle was {int(age // 60)} min ago"); sys.exit(1)
    except Exception:
        pass

print("OK"); sys.exit(0)
PY
}

MSG="$(check)"
CODE=$?

FAILS=0
[ -f "$STATE" ] && FAILS="$(cat "$STATE" 2>/dev/null || echo 0)"
case "$FAILS" in (*[!0-9]*|"") FAILS=0;; esac

notify_mac() {  # $1 title, $2 body, $3 sound (optional)
  local sound=""
  [ -n "${3:-}" ] && sound=" sound name \"$3\""
  osascript -e "display notification \"$2\" with title \"$1\"$sound" 2>/dev/null || true
}

notify_phone() {  # $1 title, $2 body, $3 priority
  [ -z "$NTFY_TOPIC" ] && return 0
  curl -fsS -m 10 -H "Title: $1" -H "Priority: ${3:-default}" -H "Tags: chart_with_upwards_trend" \
       -d "$2" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null 2>&1 || true
}

if [ "$CODE" -eq 0 ]; then
  if [ "$FAILS" -ge 2 ]; then
    notify_mac "Tajari ✅ RECOVERED" "Engine is back up and scanning."
    notify_phone "Tajari RECOVERED" "Engine is back up and scanning. Forward test is recording again." "default"
  fi
  echo 0 > "$STATE"
  exit 0
fi

FAILS=$((FAILS + 1))
echo "$FAILS" > "$STATE"
echo "[watchdog] $(date '+%F %T') check failed (${FAILS}x): $MSG"

if [ "$FAILS" -eq 2 ] || [ $((FAILS % 6)) -eq 0 ]; then
  notify_mac "Tajari 🚨 ENGINE DOWN" "$MSG — the 60-day forward test is NOT recording. It should self-restart; if this repeats, check logs/." "Sosumi"
  notify_phone "Tajari ENGINE DOWN" "$MSG — the 60-day forward test is NOT recording. Check the Mac." "high"
fi
exit 0
