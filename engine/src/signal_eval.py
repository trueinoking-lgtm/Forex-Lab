"""signal_eval.py — shared EURUSD strategy evaluation through the normal pipeline.

This is the SINGLE source of truth for "which strategies are tradeable right
now". It is used by both generate_fresh_signal.py and the tradeability watcher.

It NEVER lowers, bypasses, or alters any gate. It calls the lab's own
signals.approve_for_trading() with the configured thresholds
(min_signal_score, min_robustness, min_profit_factor) exactly as the manual
run_signals.py pipeline does. The gate reads:
  * signal score >= min_signal_score
  * robustness >= min_robustness
  * OOS return > 0
  * profit factor >= min_profit_factor
  * preferred regime matches current regime

SAFETY: this module produces analysis only. It never creates a Signal row and
never places an order.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from src import signals
from strategies.registry import REGISTRY

TREND_LIKE = ("ema_crossover", "ema_trend_pullback",
              "macd_trend_confirmation", "london_breakout")


def load_scores(scores_path) -> dict:
    import json
    from pathlib import Path
    return {r["strategy"]: r for r in json.loads(Path(scores_path).read_text())["results"]}


def evaluate_strategies(cfg, scores: dict, price: pd.Series,
                         high: pd.Series, low: pd.Series) -> dict:
    """Evaluate every strategy on live data using the normal pipeline.

    Returns a dict with:
      regime, adx, close, candle_ts (source candle timestamp, NOT run time)
      strategies: list of per-strategy dicts (direction, score, tradeable, reasons)
      best: the highest-priority tradeable candidate dict, or None
    """
    d, s = cfg["data"], cfg["signals"]
    a = float(price.iloc[-1])
    atrv = float(signals.atr(high, low, price))
    regime, adx_value = signals.classify_regime(price, high, low)
    candle_ts = str(pd.Timestamp(price.index[-1]).tz_convert("UTC")
                   if getattr(pd.Timestamp(price.index[-1]), "tzinfo", None) else
                   pd.Timestamp(price.index[-1], tz="UTC"))

    results = []
    best = None
    for name, (fn, params) in REGISTRY.items():
        sig = fn(price, **params)
        direction = int(np.sign(sig.iloc[-1]))
        if direction == 0:
            results.append({"strategy": name, "direction": 0,
                            "tradeable": False, "reasons": ["flat signal at close"],
                            "gate_reasons": ["flat signal at close"]})
            continue
        sc = scores.get(name, {})
        trend_like = name in TREND_LIKE
        preferred_regime = ("trend" if trend_like else "range") if s["regime_gate"] else "any"
        regime_allowed = (preferred_regime == "any" or preferred_regime == regime)
        sig_score = signals.score_signal(sc, regime, regime_allowed)
        gate = signals.approve_for_trading(
            sc, sc.get("robustness"), sc.get("oos_return", sc.get("total_return")),
            preferred_regime, regime, s["min_signal_score"],
            s.get("min_robustness", 0.3), s.get("min_profit_factor", 1.3))
        sl, tp = signals.compute_sl_tp(a, direction, atrv, s["sl_mult"], s["tp_mult"])
        rc = signals.risk_check(s["account"], s["risk_pct"], a, sl)
        units = float(rc.get("units", 0.0)) if rc["pass"] else 0.0
        cand = {
            "strategy": name, "direction": direction, "entry": round(a, 5),
            "stop_loss": sl, "take_profit": tp, "signal_score": sig_score,
            "regime": regime, "units": units, "tradeable": gate.tradeable,
            "reasons": gate.reasons, "gate_reasons": gate.reasons,
        }
        results.append(cand)
        # Priority: tradeable first, then highest score.
        if gate.tradeable and (best is None or sig_score > best["signal_score"]):
            best = cand

    return {
        "regime": regime, "adx": adx_value, "close": round(a, 5),
        "candle_ts": candle_ts, "strategies": results, "best": best,
    }
