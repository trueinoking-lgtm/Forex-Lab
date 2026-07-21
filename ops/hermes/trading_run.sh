#!/usr/bin/env bash
# Refresh the canonical Aether Forex Lab research backtest; no delivery here.
cd /root/aether-forex-lab/engine || exit 1
mkdir -p logs
.venv/bin/python run_backtest.py >> logs/run.log 2>&1
