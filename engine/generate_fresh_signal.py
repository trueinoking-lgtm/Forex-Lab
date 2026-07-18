#!/usr/bin/env python
"""generate_fresh_signal.py — produce ONE genuinely fresh EURUSD paper Signal row.

Uses the lab's own scoring pipeline (src/signal_eval.evaluate_strategies) on
live yfinance data: real strategy signal, ADX regime, walk-forward trade gate,
ATR-based SL/TP, and risk-sized units. The resulting Signal row has a FRESH
generated_at (run time) and a SEPARATE source candle timestamp, and is NOT
derived from / cloned from any existing signal.

SAFETY: paper_only + allow_live_orders guards; never places an order.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent))
import run_execution  # exposes _insert_fresh_signal, _db, _cfg, _now
from src import data
from src.signal_eval import evaluate_strategies, load_scores

CFG = yaml.safe_load(open("config.yaml"))


def main():
    if not CFG.get("paper_only") or CFG.get("allow_live_orders"):
        raise SystemExit("[SAFETY] paper_only must be true and allow_live_orders false.")
    symbol = "EURUSD=X"
    pair = "EURUSD"
    d = CFG["data"]

    df = data.load_pair(symbol, d["source"], timeframe=d["timeframe"],
                        lookback_days=d["lookback_days"], cache_dir=d["cache_dir"])
    price = df["close"].astype(float)
    high, low = df["high"].astype(float), df["low"].astype(float)

    scores = load_scores(Path(f"results/backtest_{symbol.replace('/', '')}.json"))
    ev = evaluate_strategies(CFG, scores, price, high, low)
    best = ev["best"]
    if best is None:
        raise SystemExit("[gen] no actionable (tradeable) signal produced for EURUSD right now")

    db = run_execution._db()
    new_ts = run_execution._now()
    new_id = run_execution._insert_fresh_signal(
        db, pair=pair, strategy=best["strategy"], direction=best["direction"],
        entry=best["entry"], stop_loss=best["stop_loss"], take_profit=best["take_profit"],
        status="paper", signal_score=best["signal_score"], regime=best["regime"],
        generated_at=new_ts, units=best["units"], original_signal_id=None,
    )
    db.commit()
    print(json.dumps({
        "status": "fresh_signal_created",
        "signal_id": new_id,
        "pair": pair,
        "strategy": best["strategy"],
        "direction": best["direction"],
        "entry": best["entry"],
        "stop_loss": best["stop_loss"],
        "take_profit": best["take_profit"],
        "signal_score": best["signal_score"],
        "regime": best["regime"],
        "units": best["units"],
        "tradeable": best["tradeable"],
        "gate_reasons": best["gate_reasons"],
        "source_candle_ts": ev["candle_ts"],
        "generated_at": new_ts,
        "note": "genuinely fresh signal from live pipeline; not cloned from any prior signal",
    }, indent=2))


if __name__ == "__main__":
    main()
