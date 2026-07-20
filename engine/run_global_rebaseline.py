#!/usr/bin/env python3
"""Frozen, deterministic global accounting rebaseline (research only)."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.accounting import accounting_metadata, legacy_metadata
from src.baseline import (buy_and_hold, circular_shift, fixed_period_momentum,
                          no_trade, sma_crossover)
from src.canonical_eval import gate_outcomes
from src.score import score_strategy
from src.trade_ledger import SHARED_NOTIONAL, extract_trades, lifecycle_metrics
from strategies.registry import REGISTRY
from run_session_breakout_research import (CORE_PAIRS, EXPECTED_SHA, FROZEN_PHASE1_PARAMS,
                                             chronological_split, load_h1)

BASE = Path(__file__).resolve().parent
DATA, RESULTS = BASE / "data", BASE / "results"
D1 = DATA / "raw_mt5_EURUSD_1d_retry.csv"
D1_SHA = "4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2"
STOP_STRATEGIES = {"trend_continuation", "rsi_range_reversion",
                   "zscore_range_reversion", "bollinger_range_reversion",
                   "session_breakout"}


def _json_value(value):
    if isinstance(value, dict): return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_json_value(v) for v in value]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def _load_d1():
    if hashlib.sha256(D1.read_bytes()).hexdigest() != D1_SHA:
        raise ValueError("D1 retry SHA-256 mismatch")
    frame = pd.read_csv(D1)
    key = "timestamp" if "timestamp" in frame else frame.columns[0]
    frame.index = pd.to_datetime(frame.pop(key), utc=True)
    frame.columns = [str(c).lower() for c in frame]
    return frame.sort_index().close.astype(float)


def _metrics(trades):
    closed = [t for t in trades if not t["still_open_at_end"]]
    life = lifecycle_metrics(trades)
    pnl = np.asarray([float(t["net_pnl"]) for t in closed], dtype=float)
    net = float(pnl.sum()) if len(pnl) else 0.0
    curve = SHARED_NOTIONAL + np.cumsum(pnl) if len(pnl) else np.asarray([SHARED_NOTIONAL])
    peak = np.maximum.accumulate(curve)
    dd = float(np.min(curve / np.where(peak == 0, 1, peak) - 1))
    ret = net / SHARED_NOTIONAL
    sharpe = (float(pnl.mean() / pnl.std() * np.sqrt(len(pnl)))
              if len(pnl) > 1 and pnl.std() else 0.0)
    scored = score_strategy({"total_return": ret, "max_drawdown": dd, "sharpe": sharpe,
        "profit_factor": life["profit_factor"] or float("nan"), "win_rate": life["win_rate"],
        "trade_count": life["trade_count"]}, [ret], 0.0, min_trades=20)
    gates = gate_outcomes({"score": scored["score"], "robustness": scored["robustness"],
                           "oos_return": ret, "profit_factor": life["profit_factor"]})
    gross = [max(0.0, float(t["net_pnl"])) for t in closed]
    return {"completed_trade_count": len(closed),
      "gross_profit_account_currency": life["gross_profit"],
      "gross_loss_account_currency": life["gross_loss"], "profit_factor": life["profit_factor"],
      "expectancy_account_currency_per_trade": life["expectancy"],
      "expectancy_return_fraction": life["expectancy"] / SHARED_NOTIONAL,
      "net_pnl_account_currency": net, "return_decimal": ret, "return_percent": ret * 100,
      "max_drawdown_decimal": dd, "robustness": scored["robustness"], "score": scored["score"],
      "largest_trade_gross_profit_fraction": max(gross, default=0) / sum(gross) if sum(gross) else 0,
      "gate_outcomes": gates, "final_classification": "rejected",
      "trade_ids": [t["trade_id"] for t in closed]}


def _legacy_metrics(trades):
    closed = [t for t in trades if not t["still_open_at_end"]]
    pnl = [float(t["price_change"]) - float(t["total_cost"]) / SHARED_NOTIONAL
           for t in closed]
    gp, gl = sum(max(x, 0) for x in pnl), -sum(min(x, 0) for x in pnl)
    return {**legacy_metadata(), "completed_trade_count": len(closed),
            "gross_profit_raw_price_units": gp, "gross_loss_raw_price_units": gl,
            "profit_factor": gp / gl if gl else None,
            "expectancy_raw_price_units_per_trade": sum(pnl) / len(pnl) if pnl else 0,
            "trade_ids": [t["trade_id"] for t in closed]}


def _entry(name, params, trades, fingerprints):
    corrected = {**accounting_metadata(has_explicit_stop=name in STOP_STRATEGIES), **_metrics(trades)}
    legacy = _legacy_metrics(trades)
    stable = legacy["trade_ids"] == corrected["trade_ids"]
    if not stable: raise RuntimeError(f"trade IDs changed for {name}")
    corrected["trade_id_sha256"] = hashlib.sha256("\n".join(corrected.pop("trade_ids")).encode()).hexdigest()
    legacy["trade_id_sha256"] = hashlib.sha256("\n".join(legacy.pop("trade_ids")).encode()).hexdigest()
    return {"strategy": name, "frozen_parameters": params, "input_fingerprints": fingerprints,
            "signals_and_timestamps_identical": True, "trade_ids_identical": stable,
            "legacy": legacy, "corrected": corrected}


def main():
    cfg = yaml.safe_load((BASE / "config.yaml").read_text())
    if not cfg.get("paper_only") or cfg.get("allow_live_orders"):
        raise SystemExit("[SAFETY] paper_only=true and allow_live_orders=false required")
    d1 = _load_d1(); entries = []
    d1_fp = {str(D1.relative_to(BASE)): D1_SHA}
    for name, (fn, params) in REGISTRY.items():
        if name == "session_breakout": continue
        signal = fn(d1, **params)
        trades = extract_trades(d1, signal, strategy=name, symbol="EURUSD",
                                spread_bps=2, slippage_bps=1)
        entries.append(_entry(name, params, trades, d1_fp))
    controls = {"no_trade": (no_trade, {}), "buy_and_hold": (buy_and_hold, {}),
                "fixed_period_momentum": (fixed_period_momentum, {"period": 20}),
                "sma_crossover": (sma_crossover, {"fast": 20, "slow": 50})}
    for name, (fn, params) in controls.items():
        trades = extract_trades(d1, fn(d1, **params), strategy=name, symbol="EURUSD",
                                spread_bps=2, slippage_bps=1)
        entries.append(_entry(name, params, trades, d1_fp))
    ema_fn, ema_params = REGISTRY["ema_crossover"]
    for seed in (7, 19, 41):
        name = f"randomized_circular_shift_seed_{seed}"
        signal = circular_shift(ema_fn(d1, **ema_params), seed)
        trades = extract_trades(d1, signal, strategy=name, symbol="EURUSD",
                                spread_bps=2, slippage_bps=1)
        entries.append(_entry(name, {"seed": seed, "source": "ema_crossover"}, trades, d1_fp))
    session_trades, h1_fp = [], {}
    session_params = dict(FROZEN_PHASE1_PARAMS)
    for pair in CORE_PAIRS:
        path = DATA / f"raw_mt5_{pair}_1h.csv"
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != EXPECTED_SHA[pair]: raise ValueError(f"{pair} H1 SHA-256 mismatch")
        h1_fp[str(path.relative_to(BASE))] = sha
        frame = chronological_split(load_h1(pair))["chronological_test"]
        fn, _ = REGISTRY["session_breakout"]
        signal = fn(frame, pair=pair, **session_params)
        session_trades += extract_trades(frame.close, signal, strategy="session_breakout",
                                         symbol=pair, spread_bps=2, commission_bps=1)
    entries.append(_entry("session_breakout", session_params, session_trades, h1_fp))
    entries.sort(key=lambda x: x["strategy"])
    payload = {**accounting_metadata(has_explicit_stop=False), "schema_version": 2,
      "purpose": "canonical_accounting_global_rebaseline", "paper_only": True,
      "allow_live_orders": False, "gates_unchanged": True, "entries": entries}
    reconciliation = {"schema_version": 2, "all_trade_ids_identical": all(x["trade_ids_identical"] for x in entries),
      "all_signals_and_timestamps_identical": True,
      "comparisons": [{"strategy": x["strategy"], "legacy": x["legacy"], "corrected": x["corrected"]} for x in entries]}
    RESULTS.mkdir(exist_ok=True)
    text = json.dumps(_json_value(payload), indent=2, sort_keys=True, allow_nan=False) + "\n"
    (RESULTS / "global_rebaseline_corrected.json").write_text(text)
    (RESULTS / "global_rebaseline_reconciliation.json").write_text(
        json.dumps(_json_value(reconciliation), indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(hashlib.sha256(text.encode()).hexdigest())


if __name__ == "__main__": main()
