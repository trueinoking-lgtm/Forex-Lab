#!/usr/bin/env python
"""run_backtest.py — walk-forward backtest + scoring for all strategies.

Usage: python run_backtest.py [--pair SYMBOL]
Writes engine/results/backtest_<pair>.json (read by the Next.js app).
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path
import yaml
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from src import data, backtest, metrics, score, log
from src.paper_sim import overfitting_flags
from strategies.registry import REGISTRY, build_signal

CFG = yaml.safe_load(open("config.yaml"))


def ctx_for(cost_bps):
    bt = CFG["backtest"]
    return {"walk_forward": bt["walk_forward"], "cost_bps": cost_bps,
            "initial_capital": bt["initial_capital"],
            "periods_per_year": bt["periods_per_year"], "risk_free_rate": bt["risk_free_rate"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default=None)
    args = ap.parse_args()
    d = CFG["data"]
    symbol = args.pair or d["symbol"]
    cost = CFG["cost"]
    cost_bps = cost["fee_bps"] + cost["slippage_bps"] + cost["spread_bps"]
    ctx = ctx_for(cost_bps)

    log.log(f"[backtest] loading {symbol} via {d['source']}")
    df = data.load_pair(symbol, d["source"], timeframe=d["timeframe"],
                        lookback_days=d["lookback_days"], cache_dir=d["cache_dir"])
    price = df["close"].astype(float)
    log.log(f"[backtest] {len(price)} bars {price.index[0].date()}..{price.index[-1].date()}")

    bh = backtest.walk_forward_bh(price, ctx)
    bh_ret = bh["metrics"].get("total_return", 0.0)

    results = []
    for name, (fn, params) in REGISTRY.items():
        # full-period (in-sample) return for the OOS gap
        ins = backtest.run(price, fn(price, **params), cost_bps, ctx["initial_capital"],
                           ctx["periods_per_year"], ctx["risk_free_rate"])
        ins_ret = ins["metrics"]["total_return"]
        oos = backtest.walk_forward(price, lambda p, **k: fn(p, **params), ctx)
        sc = score.score_strategy(oos["metrics"], oos["window_returns"], ins_ret,
                                  min_trades=CFG["backtest"].get("min_trades", 20))
        sc["strategy"] = name
        sc["pair"] = symbol
        sc["timeframe"] = d["timeframe"]
        sc["in_sample_return"] = round(ins_ret, 4)
        sc["oos_return"] = round(oos["metrics"].get("total_return", 0.0), 4)
        sc["bh_oos_return"] = round(bh_ret, 4)
        sc["beats_bh"] = bool(oos["metrics"].get("total_return", 0) > bh_ret)
        sc["overfitting_flags"] = overfitting_flags(
            oos["metrics"], in_sample_return=ins_ret,
            oos_return=oos["metrics"].get("total_return", 0.0))
        min_trades = CFG["backtest"].get("min_trades", 20)
        sc["min_trades_warning"] = (f"Insufficient sample: {sc.get('trade_count', 0)} "
                                    f"trades; minimum is {min_trades}."
                                    if sc.get("trade_count", 0) < min_trades else None)
        results.append(sc)
        log.log(f"[backtest] {name:22s} score={sc['score']:5.1f} "
                f"oos={sc['oos_return']:+.3f} rob={sc['robustness']:.2f}")

    results.sort(key=lambda r: r["score"], reverse=True)
    out = {"generated_at": str(pd.Timestamp.now(tz="UTC")), "pair": symbol,
           "timeframe": d["timeframe"], "cost_bps": cost_bps, "bh_oos_return": bh_ret,
           "results": results}
    Path("results").mkdir(exist_ok=True)
    path = Path(f"results/backtest_{symbol.replace('/', '')}.json")
    path.write_text(json.dumps(out, indent=2))
    log.log(f"[backtest] wrote {path}")
    # print best
    if results:
        b = results[0]
        log.log(f"[backtest] BEST: {b['strategy']} score={b['score']} "
                f"beats_bh={b['beats_bh']}")


if __name__ == "__main__":
    main()
