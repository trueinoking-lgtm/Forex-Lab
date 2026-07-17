#!/usr/bin/env python
"""Run held-out validation and readiness gates. Paper-only; no broker access."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd
import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from src import backtest, data, log, score
from src.live_readiness import readiness_report
from src.validation import directional_accuracy, held_out_validate
from strategies.registry import REGISTRY

CFG = yaml.safe_load((BASE / "config.yaml").read_text())


def ctx_for(cost_bps):
    bt = CFG["backtest"]
    return {"walk_forward": bt["walk_forward"], "cost_bps": cost_bps,
            "initial_capital": bt["initial_capital"],
            "periods_per_year": bt["periods_per_year"],
            "risk_free_rate": bt["risk_free_rate"]}


def _json_safe(value):
    """Recursively convert numpy values and non-finite metrics to valid JSON."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="EURUSD=X")
    parser.add_argument("--cutoff", help="held-out start date (YYYY-MM-DD)")
    parser.add_argument("--train-lookback-days", type=int, default=756)
    parser.add_argument("--db", default="forex_lab.db", help="reserved for report ingestion")
    args = parser.parse_args()
    if not CFG.get("paper_only") or CFG.get("allow_live_orders"):
        raise SystemExit("[SAFETY] paper_only must be true and allow_live_orders false. Refusing.")

    d, cost = CFG["data"], CFG["cost"]
    cost_bps = cost["fee_bps"] + cost["slippage_bps"] + cost["spread_bps"]
    ctx = ctx_for(cost_bps)
    try:
        frame = data.load_pair(args.pair, d["source"], timeframe=d["timeframe"],
                               lookback_days=d["lookback_days"],
                               cache_dir=str(BASE / d["cache_dir"]))
    except Exception as exc:
        raise SystemExit(f"[validate] unable to load {args.pair}: {exc}") from exc
    price = frame["close"].astype(float)
    cutoff = pd.Timestamp(args.cutoff) if args.cutoff else price.index[-1] - pd.Timedelta(days=365)
    # Reserve the post-cutoff window from ALL development scoring (in-sample,
    # walk-forward, BH) so the held-out result is not contaminated by data it is
    # later compared against. held_out_validate() re-splits at the cutoff itself.
    dev = price[price.index < cutoff]

    results = []
    failed = 0
    for name, (fn, params) in REGISTRY.items():
        try:
            signal_fn = lambda p, _fn=fn, _params=params, **k: _fn(p, **_params)
            ins = backtest.run(dev, signal_fn(dev), cost_bps, ctx["initial_capital"],
                               ctx["periods_per_year"], ctx["risk_free_rate"])
            wf = backtest.walk_forward(dev, signal_fn, ctx)
            scored = score.score_strategy(wf["metrics"], wf["window_returns"],
                                          ins["metrics"]["total_return"],
                                          min_trades=CFG["backtest"].get("min_trades", 20))
            held_out = held_out_validate(price, signal_fn, ctx, cutoff,
                                         args.train_lookback_days)
            accuracy = directional_accuracy(held_out.get("trades", []))
            oos_return = scored.get("oos_return", scored.get("total_return"))
            report = readiness_report(
                walk_forward_score=scored["score"], robustness=scored["robustness"],
                oos_return=oos_return, held_out_metrics=held_out["metrics"],
                directional_accuracy=accuracy, regime_fit=True)
            metrics = held_out["metrics"]
            results.append({
                "strategy": name, "walk_forward_score": scored["score"],
                "robustness": scored["robustness"], "oos_return": oos_return,
                "held_out_return": metrics.get("total_return"),
                "held_out_max_dd": metrics.get("max_drawdown"),
                "profit_factor": metrics.get("profit_factor"),
                "directional_hit_rate": accuracy["hit_rate"], "go": report["go"],
                "readiness_score": report["score"], "reasons": report["reasons"],
            })
        except Exception as exc:
            failed += 1
            log.log(f"[validate] skip {name}: {exc}")
            results.append({
                "strategy": name, "go": False, "error": str(exc),
                "reasons": ["evaluation failed"], "readiness_score": 0.0,
            })
    results.sort(key=lambda item: (item["go"], item["readiness_score"]), reverse=True)
    payload = {"generated_at": str(pd.Timestamp.now(tz="UTC")), "pair": args.pair,
               "cutoff": str(cutoff), "paper_only": True, "results": results}
    if failed:
        payload["evaluation_errors"] = failed
    output_dir = BASE / "results"
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"readiness_{args.pair.replace('/', '')}.json"
    path.write_text(json.dumps(_json_safe(payload), indent=2, allow_nan=False))
    log.log("strategy                 wf_score  robust  oos_ret  held_ret  hit_rate  go")
    for row in results:
        if "error" in row:
            log.log(f"{row['strategy']:24s} {'ERROR':>8s} {row['error'][:40]}")
            continue
        log.log(f"{row['strategy']:24s} {row['walk_forward_score']:8.1f} "
                f"{row['robustness']:7.2f} {row['oos_return']:8.3f} "
                f"{row['held_out_return']:9.3f} {row['directional_hit_rate']:8.2f} "
                f"{'GO' if row['go'] else 'NO-GO'}")
    log.log(f"[validate] wrote {path}")
    # Fail closed: if every strategy failed evaluation, signal nonzero so callers
    # (cron, CI) know the readiness report is incomplete, not clean.
    if failed and failed == len(results):
        raise SystemExit(f"[validate] all {failed} strategies failed evaluation")


if __name__ == "__main__":
    main()
