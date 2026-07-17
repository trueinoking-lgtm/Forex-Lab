#!/usr/bin/env python
"""run_signals.py — generate scored PAPER signals for the latest close.

SAFETY: paper_only + allow_live_orders double-guard. No order is ever placed.
Writes engine/results/signals_<pair>.json for the Next.js app + decision journal.
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path
import yaml
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from src import data, backtest, metrics, score, signals, log
from strategies.registry import REGISTRY, build_signal

CFG = yaml.safe_load(open("config.yaml"))

if not CFG.get("paper_only") or CFG.get("allow_live_orders"):
    raise SystemExit("[SAFETY] paper_only must be true and allow_live_orders false. Refusing.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default=None)
    args = ap.parse_args()
    d, s = CFG["data"], CFG["signals"]
    symbol = args.pair or d["symbol"]
    cost = CFG["cost"]
    cost_bps = cost["fee_bps"] + cost["slippage_bps"] + cost["spread_bps"]

    df = data.load_pair(symbol, d["source"], timeframe=d["timeframe"],
                        lookback_days=d["lookback_days"], cache_dir=d["cache_dir"])
    price = df["close"].astype(float)
    high, low = df["high"].astype(float), df["low"].astype(float)

    # load latest backtest scores (produced by run_backtest.py)
    score_path = Path(f"results/backtest_{symbol.replace('/', '')}.json")
    if not score_path.exists():
        raise SystemExit("[SAFETY] no backtest scores yet — run backtest first")
    scores = {r["strategy"]: r for r in json.loads(score_path.read_text())["results"]}

    regime, adx_value = signals.classify_regime(price, high, low)
    a = price.iloc[-1]
    atrv = signals.atr(high, low, price)

    out_signals = []
    journal = []
    for name, (fn, params) in REGISTRY.items():
        sig = fn(price, **params)
        direction = int(np.sign(sig.iloc[-1]))
        if direction == 0:
            journal.append({"strategy": name, "action": "skip",
                            "reason": "flat signal at close"})
            continue
        sc = scores.get(name, {})
        # Momentum-like strategies prefer trends; mean-reversion prefers ranges.
        trend_like = name in ("ema_crossover", "ema_trend_pullback",
                              "macd_trend_confirmation", "london_breakout")
        preferred_regime = ("trend" if trend_like else "range") \
            if s["regime_gate"] else "any"
        regime_allowed = (preferred_regime == "any" or preferred_regime == regime)
        sig_score = signals.score_signal(sc, regime, regime_allowed)
        gate = signals.approve_for_trading(
            sc, sc.get("robustness"), sc.get("oos_return", sc.get("total_return")),
            preferred_regime, regime, s["min_signal_score"],
            s.get("min_robustness", 0.3), s.get("min_profit_factor", 1.3))
        sl, tp = signals.compute_sl_tp(a, direction, atrv, s["sl_mult"], s["tp_mult"])
        rc = signals.risk_check(s["account"], s["risk_pct"], a, sl)
        if not rc["pass"]:
            journal.append({"strategy": name, "action": "skip",
                            "reason": f"risk_check failed: {rc['reason']}"})
            continue
        units = rc.get("units", 0.0)
        psig = signals.PaperSignal(
            pair=symbol, strategy=name, direction=direction, entry=round(a, 5),
            stop_loss=sl, take_profit=tp, signal_score=sig_score,
            regime=regime, timestamp=str(pd.Timestamp.now(tz="UTC")),
            units=units)
        signal_record = psig.to_dict()
        signal_record["tradeable"] = gate.tradeable
        out_signals.append(signal_record)
        journal.append({"strategy": name, "action": "paper_signal",
                        "direction": direction, "entry": a, "sl": sl, "tp": tp,
                        "units": units, "signal_score": sig_score,
                        "tradeable": gate.tradeable,
                        "reason": "approved for trading" if gate.tradeable else
                                  "; ".join(gate.reasons)})

    out = {"generated_at": str(pd.Timestamp.now(tz="UTC")), "pair": symbol,
           "regime": regime, "adx": adx_value, "close": round(a, 5), "paper_only": True,
           "signals": out_signals, "journal": journal}
    Path("results").mkdir(exist_ok=True)
    Path(f"results/signals_{symbol.replace('/', '')}.json").write_text(json.dumps(out, indent=2))
    log.log(f"[signals] regime={regime} paper_signals={len(out_signals)} "
            f"(paper_only={CFG['paper_only']})")
    for j in journal:
        log.log(f"[signals] {j['strategy']:22s} {j['action']}: {j['reason']}")


if __name__ == "__main__":
    main()
