#!/usr/bin/env bash
# run_watcher.sh — cwd-independent launcher for the tradeability watcher.
# Safe to call from cron (which may run with $HOME as cwd and a minimal PATH).
#
# The watcher needs pandas/yfinance (heavy deps) that only exist in a specific
# venv. Cron's minimal PATH would otherwise resolve `python3` to a bare
# /usr/bin/python3 without those deps and crash silently. We pin the interpreter
# explicitly and VALIDATE it before running — no silent fallback.
set -u

PROJECT_DIR="/root/aether-forex-lab"
ENGINE_DIR="$PROJECT_DIR/engine"
ENV_FILE="$ENGINE_DIR/.env"

# Optional override; defaults to the only Python on this host with the engine deps.
PYTHON_BIN="${WATCHER_PYTHON:-/usr/local/lib/hermes-agent/venv/bin/python3}"

# 1) cd to project root (absolute, cwd-independent).
cd "$PROJECT_DIR" || { echo "cd $PROJECT_DIR failed" >&2; exit 1; }

# 2) Load engine/.env via absolute path (exports REMOTE_MT5_BRIDGE_* etc.).
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

# 3) Validate the interpreter before doing anything.
if [ ! -x "$PYTHON_BIN" ]; then
  logger -t aether-watcher "FATAL: interpreter not executable: $PYTHON_BIN"
  echo "interpreter not executable: $PYTHON_BIN" >&2
  exit 2
fi

if ! "$PYTHON_BIN" -c "import pandas, yfinance" >/dev/null 2>&1; then
  logger -t aether-watcher "FATAL: $PYTHON_BIN cannot import pandas/yfinance (wrong venv?)"
  echo "$PYTHON_BIN missing engine deps (pandas/yfinance)" >&2
  exit 3
fi

# 4) exec the watcher using absolute paths. Never falls back to /usr/bin/python3.
exec "$PYTHON_BIN" "$ENGINE_DIR/tradeability_watcher.py"
