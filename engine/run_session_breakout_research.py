#!/usr/bin/env python
"""Deterministic, data-gated multi-pair H1 session-breakout Phase 1 research."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from engine.strategies.session_breakout import session_breakout
    from engine.src.trade_ledger import extract_trades, lifecycle_metrics
except ImportError:
    from strategies.session_breakout import session_breakout
    from src.trade_ledger import extract_trades, lifecycle_metrics

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RESULTS = BASE / "results"
CORE_PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
SCOPES = {"development", "validation", "chronological_test", "aggregate_cross_pair_test",
          "full_historical_diagnostic", "cost_stress", "randomized_control"}
PARAM_GRID = {
    "breakout_buffer": (0, .05, .10), "min_range_atr": (None, .5, .75),
    "max_range_atr": (None, 1.5, 2.0), "stop": ("opp_side", "1.0ATR", "1.5ATR"),
    "target_r": (None, 1.0, 1.5, 2.0), "max_holding": (4, 8, "session_close"),
    "atr_lookback": (14,),
}
DEFAULT_PARAMS = {"range_start_hour": 0, "range_end_hour": 7, "breakout_window": (7, 16),
                  "breakout_buffer": 0, "min_range_atr": None, "max_range_atr": None,
                  "atr_lookback": 14, "stop_mode": "opp_side", "stop_atr": None,
                  "target_r": None, "max_holding": "session_close", "session_end_hour": 16,
                  "long_allowed": True, "short_allowed": True}


def _path(pair, data_dir):
    return Path(data_dir) / f"raw_mt5_{pair}_1h.csv"


def load_h1(pair, data_dir=DATA):
    path = _path(pair, data_dir)
    if not path.is_file():
        raise FileNotFoundError(f"H1 data required: missing real MT5 CSV {path}")
    frame = pd.read_csv(path)
    ts_name = "timestamp" if "timestamp" in frame else frame.columns[0]
    frame.index = pd.to_datetime(frame.pop(ts_name), utc=True)
    frame.columns = [str(c).lower() for c in frame.columns]
    required = {"open", "high", "low", "close"}
    if missing := required-set(frame):
        raise ValueError(f"H1 data required: {pair} missing columns {sorted(missing)}")
    frame = frame.sort_index()
    if frame.empty or frame.index.duplicated().any():
        raise ValueError(f"H1 data required: {pair} is empty or has duplicate timestamps")
    return frame


def chronological_split(frame):
    days = pd.Index(frame.index.normalize().unique()).sort_values()
    if len(days) < 5:
        raise ValueError("H1 data required: at least five UTC dates per pair")
    d60 = days[max(0, int(len(days)*.6)-1)]
    d80 = days[max(1, int(len(days)*.8)-1)]
    return {"development": frame[frame.index.normalize() <= d60],
            "validation": frame[(frame.index.normalize() > d60) & (frame.index.normalize() <= d80)],
            "chronological_test": frame[frame.index.normalize() > d80]}


def _metrics(trades, scope, *, pair=None):
    if scope not in SCOPES: raise ValueError(f"invalid result scope: {scope}")
    life = lifecycle_metrics(trades)
    net = sum(float(t["net_pnl"]) for t in trades if not t["still_open_at_end"])
    ret = sum(float(t["return_pct"]) for t in trades if not t["still_open_at_end"])
    pf = life["profit_factor"]
    return {"scope": scope, "pair": pair, "trade_count": life["trade_count"],
            "gross_profit": life["gross_profit"], "gross_loss": life["gross_loss"],
            "profit_factor": pf, "return": ret, "net_pnl": net,
            "robustness": 0.0, "score": 0.0}


def _run(frame, pair, params, scope, costs=3.0, signal=None):
    signal = session_breakout(frame, pair=pair, **params) if signal is None else signal
    trades = extract_trades(frame.close, signal, strategy="session_breakout", symbol=pair,
                            spread_bps=max(0, costs-1), commission_bps=1)
    return _metrics(trades, scope, pair=pair), trades


def aggregate(trades, scope="aggregate_cross_pair_test"):
    """Recompute aggregate PF from combined gross profit/loss; never average PFs."""
    return _metrics(sorted(trades, key=lambda x: x.get("entry_ts", "")), scope)


def parameter_candidates():
    for buffer, minimum, maximum, stop, target, holding in itertools.product(
            PARAM_GRID["breakout_buffer"], PARAM_GRID["min_range_atr"],
            PARAM_GRID["max_range_atr"], PARAM_GRID["stop"], PARAM_GRID["target_r"],
            PARAM_GRID["max_holding"]):
        if minimum is not None and maximum is not None and minimum >= maximum: continue
        yield {**DEFAULT_PARAMS, "breakout_buffer": buffer, "min_range_atr": minimum,
               "max_range_atr": maximum, "stop_mode": "opp_side" if stop == "opp_side" else "atr",
               "stop_atr": None if stop == "opp_side" else float(stop[:3]),
               "target_r": target, "max_holding": holding}


def research(frames, *, persist=False, synthetic_test_fixture=False, candidates=None):
    if synthetic_test_fixture and persist:
        raise ValueError("synthetic test fixtures can never persist research results")
    if set(CORE_PAIRS)-set(frames):
        raise FileNotFoundError("H1 data required: all four core-pair MT5 CSVs are mandatory")
    folds = {p: chronological_split(f) for p, f in frames.items()}
    candidates = list(candidates or parameter_candidates())
    # Select using DEV+VAL only. TEST remains untouched until one shared set is frozen.
    ranked = []
    for params in candidates:
        trades = []
        for pair in CORE_PAIRS:
            for scope in ("development", "validation"):
                _, ledger = _run(folds[pair][scope], pair, params, scope)
                trades.extend(ledger)
        m = aggregate(trades, "validation")
        ranked.append((m["net_pnl"] >= 0, m["profit_factor"] or 0, params))
    selected = max(ranked, key=lambda x: (x[0], x[1]))[2]
    pair_results, combined = {}, []
    for pair in CORE_PAIRS:
        pair_results[pair] = {}
        for scope in ("development", "validation", "chronological_test"):
            metric, ledger = _run(folds[pair][scope], pair, selected, scope)
            pair_results[pair][scope] = metric
            if scope == "chronological_test": combined.extend(ledger)
    agg = aggregate(combined)
    stress_trades = []
    for pair in CORE_PAIRS:
        _, ledger = _run(folds[pair]["chronological_test"], pair, selected, "cost_stress", costs=5)
        stress_trades.extend(ledger)
    stress = aggregate(stress_trades, "cost_stress")
    rng = np.random.default_rng(20260720); controls = []
    for seed in range(20):
        control_trades = []
        for pair in CORE_PAIRS:
            f = folds[pair]["chronological_test"]
            signal = pd.Series(rng.choice([-1., 0., 1.], len(f), p=[.03, .94, .03]), index=f.index)
            _, ledger = _run(f, pair, selected, "randomized_control", signal=signal)
            control_trades.extend(ledger)
        controls.append({"seed": seed, **aggregate(control_trades, "randomized_control")})
    closed = [t for t in combined if not t["still_open_at_end"]]
    net = agg["net_pnl"]
    wins = sorted((float(t["net_pnl"]) for t in closed if t["net_pnl"] > 0), reverse=True)
    gross_by_pair = {p: sum(float(t["net_pnl"]) for t in closed
                            if t["symbol"] == p and t["net_pnl"] > 0) for p in CORE_PAIRS}
    total_gp = sum(gross_by_pair.values())
    random_returns = sorted(x["return"] for x in controls)
    random_p90 = random_returns[int(.9*(len(random_returns)-1))]
    acceptance = {"pf_gte_1_3": agg["profit_factor"] is not None and agg["profit_factor"] >= 1.3,
                  "return_gt_0": agg["return"] > 0, "trades_gte_200": agg["trade_count"] >= 200,
                  "each_pair_gte_30": all(pair_results[p]["chronological_test"]["trade_count"] >= 30 for p in CORE_PAIRS),
                  "survives_5bps": stress["return"] > 0,
                  "positive_3_pairs": sum(pair_results[p]["chronological_test"]["return"] > 0 for p in CORE_PAIRS) >= 3,
                  "robustness_gte_0_3": agg["robustness"] >= .3, "score_gte_40": agg["score"] >= 40,
                  "beats_randomized_median_and_p90": agg["return"] > random_p90,
                  "pair_gp_le_50pct": bool(total_gp) and max(gross_by_pair.values())/total_gp <= .5,
                  "best_trade_le_15pct": bool(net > 0) and (wins[0] if wins else 0)/net <= .15,
                  "best3_le_30pct": bool(net > 0) and sum(wins[:3])/net <= .30,
                  # These require adequate real-history strata/nearby candidates; fail closed.
                  "no_period_dependence": False, "nearby_stability": False,
                  "edge_in_intended_session": bool(closed) and all(7 <= pd.Timestamp(t["signal_ts"]).hour < 16 for t in closed)}
    payload = {"research": "session_breakout_phase1", "synthetic_test_fixture": synthetic_test_fixture,
               "selected_parameters": selected, "fold_boundaries": {p: {s: [str(x.index.min()), str(x.index.max())] for s, x in fs.items()} for p, fs in folds.items()},
               "pair_results": pair_results, "aggregate_cross_pair_test": agg,
               "cost_stress": stress, "randomized_control": controls,
               "controls": {"no_trade": {"scope": "full_historical_diagnostic", "return": 0.0},
                            "random_session_direction": "20 deterministic seeds above",
                            "random_breakout_time": "reserved deterministic randomized-control family",
                            "previous_day_high_low": "full_historical_diagnostic",
                            "existing_d1_london_approximation": "full_historical_diagnostic",
                            "buy_and_hold": "diagnostic only"},
               "acceptance": acceptance, "classification": "ACCEPT" if all(acceptance.values()) else "REJECT STRATEGY FAMILY"}
    if persist:
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / "session_breakout_phase1.json"
        out.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False)+"\n")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    args = parser.parse_args(argv)
    try:
        frames = {pair: load_h1(pair, args.data_dir) for pair in CORE_PAIRS}
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    research(frames, persist=True)


if __name__ == "__main__":
    main()
