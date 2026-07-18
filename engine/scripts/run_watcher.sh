#!/usr/bin/env bash
# run_watcher.sh — cwd-independent launcher for the tradeability watcher.
# Safe to call from cron (which may run with $HOME as cwd).
set -u

PROJECT_DIR="/root/aether-forex-lab"
ENGINE_DIR="$PROJECT_DIR/engine"
ENV_FILE="$ENGINE_DIR/.env"
LOCK_FD=200

# 1) cd to project root (absolute, cwd-independent).
cd "$PROJECT_DIR" || { echo "cd $PROJECT_DIR failed" >&2; exit 1; }

# 2) Load engine/.env via absolute path (exports REMOTE_MT5_BRIDGE_* etc.).
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

# 3) Prefer the project virtualenv Python if it exists.
if [ -x "$ENGINE_DIR/venv/bin/python" ]; then
  PY="$ENGINE_DIR/venv/bin/python"
elif [ -x "$PROJECT_DIR/venv/bin/python" ]; then
  PY="$PROJECT_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "no python3 found" >&2; exit 1
fi

# 4) exec the watcher using an absolute path.
exec "$PY" "$ENGINE_DIR/tradeability_watcher.py"
