#!/usr/bin/env bash
#
# Supervised launcher for the Tajari trading engine — built for the 60-day
# unattended forward test.
#
#   • NO --reload (the dev flag restarts the process on every file save —
#     never use it for the campaign run)
#   • Auto-restarts the backend if it ever crashes, with a short backoff
#   • caffeinate keeps the Mac awake while the engine runs (a sleeping
#     laptop is the #1 killer of long-running paper tests)
#   • Logs to logs/engine-YYYY-MM-DD.log, one file per day
#
# Usage:
#   ./scripts/run_engine.sh            # foreground (leave the terminal open)
#   nohup ./scripts/run_engine.sh &    # survive closing the terminal
#
# For fully unattended operation (survives logout + reboot), install the
# launchd job instead — see docs/FORWARD_TEST.md.

set -u
cd "$(dirname "$0")/.."

mkdir -p logs data

HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-8000}"
BACKOFF=5

# launchd jobs get a bare PATH where `python3` is often Apple's
# CommandLineTools build with no packages installed. Hunt for an interpreter
# that can actually import uvicorn instead of trusting PATH. Override with
# TAJARI_PYTHON=/path/to/python3 if needed.
find_python() {
  local p
  for p in "${TAJARI_PYTHON:-}" \
           /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
           /opt/homebrew/bin/python3 \
           /usr/local/bin/python3 \
           "$(command -v python3 2>/dev/null)"; do
    if [ -n "$p" ] && [ -x "$p" ] && "$p" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

PY="$(find_python)" || {
  echo "[run_engine] FATAL: no python3 with uvicorn+fastapi found." \
       "Install deps (pip3 install -r requirements.txt) or set TAJARI_PYTHON=/path/to/python3." \
    | tee -a "logs/engine-$(date +%Y-%m-%d).log"
  sleep 300   # throttle launchd's KeepAlive respawn so the log message repeats calmly
  exit 1
}
echo "[run_engine] using python: $PY"

# caffeinate exists on macOS only; run bare uvicorn elsewhere.
RUNNER=""
if command -v caffeinate >/dev/null 2>&1; then
  RUNNER="caffeinate -is"
fi

echo "[run_engine] starting supervised engine on ${HOST}:${PORT} (Ctrl-C to stop)"

while true; do
  LOG="logs/engine-$(date +%Y-%m-%d).log"
  echo "[run_engine] $(date '+%F %T') launching backend → ${LOG}"
  # shellcheck disable=SC2086
  $RUNNER "$PY" -m uvicorn backend.main:app --host "$HOST" --port "$PORT" >>"$LOG" 2>&1
  CODE=$?
  echo "[run_engine] $(date '+%F %T') backend exited with code ${CODE} — restarting in ${BACKOFF}s" | tee -a "$LOG"
  sleep "$BACKOFF"
  # Gentle exponential backoff, capped at 60s, reset after a clean hour is
  # not tracked — simple and good enough for a paper engine.
  BACKOFF=$(( BACKOFF < 60 ? BACKOFF * 2 : 60 ))
done
