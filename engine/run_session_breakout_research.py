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
    from engine.src.score import score_strategy
except ImportError:
    from strategies.session_breakout import session_breakout
    from src.trade_ledger import extract_trades, lifecycle_metrics
    from src.score import score_strategy

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
EXPECTED_SHA = {"EURUSD": "80cc20e9de10f929619902d618a32035f45d557751153d16484de46d8d5fcfc1",
 "GBPUSD": "99a2564ae0040d6c47ec20d1ce84c82a464be44dafac05898ea7e2e53d1fa789",
 "USDJPY": "3aad2f78b5b06f39ac7804d33845c40e31d2d00073937e2df8eb51512802db60",
 "AUDUSD": "776a10f7326ba04bf68a7c95011aedeebee693b0c5eb22d2ea22a98332bb94a7"}


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


def verify_input(pair, data_dir=DATA):
    path = _path(pair, data_dir); manifest_path = path.with_suffix(".manifest.json")
    if not path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"H1 data required: missing real MT5 CSV/manifest for {pair}")
    raw_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if raw_sha != EXPECTED_SHA[pair]:
        raise ValueError(f"{pair} raw SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text())
    forbidden = {"account", "account_number", "login", "password", "credential", "token"}
    if any(k.lower() in forbidden for k in manifest for k in [str(k)]):
        raise ValueError(f"{pair} manifest contains account/credential metadata")
    if not (manifest.get("symbol") == pair and manifest.get("timeframe") == "1h" and
            manifest.get("timezone") == "UTC" and manifest.get("source") == "MetaTrader5 demo history"):
        raise ValueError(f"{pair} manifest identity mismatch")
    raw = pd.read_csv(path); ts_name = "timestamp" if "timestamp" in raw else raw.columns[0]
    ts = pd.to_datetime(raw[ts_name], utc=True, errors="raise")
    cols = {c: pd.to_numeric(raw[c], errors="raise") for c in ("open", "high", "low", "close")}
    volume = pd.to_numeric(raw["volume"], errors="raise") if "volume" in raw else pd.Series(0, index=raw.index)
    finite = np.isfinite(np.column_stack(list(cols.values()))).all(axis=1)
    invalid = (~finite | (cols["open"] <= 0) | (cols["high"] <= 0) |
               (cols["low"] <= 0) | (cols["close"] <= 0) |
               (cols["high"] < cols["open"]) | (cols["high"] < cols["close"]) |
               (cols["low"] > cols["open"]) | (cols["low"] > cols["close"]) |
               (cols["high"] < cols["low"]))
    if invalid.any() or not ts.is_monotonic_increasing or ts.duplicated().any():
        raise ValueError(f"{pair} unresolved OHLC/timestamp defect")
    # Delivered retrieval was during the 19:00 candle.  Apply the exporter's
    # interval-close rule without rewriting the immutable CSV.
    excluded = bool(len(ts) and ts.iloc[-1] == pd.Timestamp("2026-07-20T19:00:00Z"))
    evaluated_raw = raw.iloc[:-1].copy() if excluded else raw.copy()
    frame = evaluated_raw.copy(); frame.index = pd.to_datetime(frame.pop(ts_name), utc=True)
    frame.columns = [str(c).lower() for c in frame.columns]
    diffs = ts.diff().dropna(); long_gaps = []
    for i in np.flatnonzero((diffs > pd.Timedelta(hours=1)).to_numpy()):
        before, after = ts.iloc[i], ts.iloc[i + 1]
        weekend = before.weekday() == 4 or after.weekday() in (0, 6)
        if diffs.iloc[i] > pd.Timedelta(hours=72) and not weekend:
            long_gaps.append({"after": before.isoformat(), "hours": diffs.iloc[i].total_seconds()/3600})
    evaluated_sha = hashlib.sha256(evaluated_raw.to_csv(index=False).encode()).hexdigest()
    finding = {"pair": pair, "raw_sha256": raw_sha, "evaluated_sha256": evaluated_sha,
      "raw_rows": len(raw), "evaluated_rows": len(frame), "raw_start": ts.iloc[0].isoformat(),
      "raw_end": ts.iloc[-1].isoformat(), "evaluated_end": frame.index[-1].isoformat(),
      "incomplete_final_bar_excluded": excluded, "ascending": bool(ts.is_monotonic_increasing),
      "duplicate_timestamps": int(ts.duplicated().sum()), "invalid_ohlc": int(invalid.sum()),
      "negative_volume": int((volume < 0).sum()), "gap_count": int((diffs > pd.Timedelta(hours=1)).sum()),
      "unexpected_long_gaps": long_gaps, "deterministic_parse": True, "manifest": manifest}
    return frame, finding


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
    closed = [t for t in trades if not t["still_open_at_end"]]
    returns = np.asarray([float(t["return_pct"]) for t in closed])
    curve = np.cumprod(1 + returns) if len(returns) else np.asarray([1.])
    peak = np.maximum.accumulate(curve)
    drawdown = float(np.min(curve / peak - 1))
    sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(len(returns))) if len(returns) > 1 and np.std(returns) else 0.
    scored = score_strategy({"total_return": ret, "sharpe": sharpe,
        "profit_factor": pf if pf is not None else float("nan"),
        "win_rate": life["win_rate"], "trade_count": life["trade_count"],
        "max_drawdown": drawdown}, [ret], 0., min_trades=20)
    exposure = (sum(int(t["holding_bars"]) for t in closed) /
                max(1, sum(int(t["holding_bars"]) for t in closed) + len(closed)))
    directions = {d: lifecycle_metrics([t for t in trades if t.get("direction") == d])
                  for d in ("long", "short")}
    return {"scope": scope, "pair": pair, "trade_count": life["trade_count"],
            "completed_trades": life["trade_count"], "open_trades": life["open_trade_count"],
            "wins": life["wins"], "losses": life["losses"], "win_rate": life["win_rate"],
            "gross_profit": life["gross_profit"], "gross_loss": life["gross_loss"],
            "profit_factor": pf, "return": ret, "net_pnl": net,
            "expectancy": life["expectancy"], "max_drawdown": drawdown,
            "exposure": exposure, "robustness": scored["robustness"],
            "score": scored["score"], "long_short": directions}


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
    staged = candidates is None
    if staged:
        # Preregistered staged subfamily evaluation: screen all 27 range-filter
        # combinations with the neutral exit, then expand every frozen exit
        # combination for the three best screens. Bounds are never widened.
        screens = []
        for buffer, minimum, maximum in itertools.product(
                PARAM_GRID["breakout_buffer"], PARAM_GRID["min_range_atr"],
                PARAM_GRID["max_range_atr"]):
            params = {**DEFAULT_PARAMS, "breakout_buffer": buffer,
                      "min_range_atr": minimum, "max_range_atr": maximum}
            ledgers = []
            for pair in CORE_PAIRS:
                for scope in ("development", "validation"):
                    ledgers += _run(folds[pair][scope], pair, params, scope)[1]
            metric = aggregate(ledgers, "validation")
            screens.append((metric["robustness"] * np.sign(metric["score"]),
                            metric["profit_factor"] or 0., params))
        best_filters = [x[2] for x in sorted(screens, reverse=True,
                                             key=lambda x: (x[0], x[1]))[:3]]
        candidates = []
        for base in best_filters:
            for stop, target, holding in itertools.product(
                    PARAM_GRID["stop"], PARAM_GRID["target_r"], PARAM_GRID["max_holding"]):
                candidates.append({**base,
                    "stop_mode": "opp_side" if stop == "opp_side" else "atr",
                    "stop_atr": None if stop == "opp_side" else float(stop[:3]),
                    "target_r": target, "max_holding": holding})
    candidates = list(candidates)
    # Select using DEV+VAL only. TEST remains untouched until one shared set is frozen.
    ranked = []
    for params in candidates:
        trades = []
        for pair in CORE_PAIRS:
            for scope in ("development", "validation"):
                _, ledger = _run(folds[pair][scope], pair, params, scope)
                trades.extend(ledger)
        m = aggregate(trades, "validation")
        eligible = (m["return"] > 0 and (m["profit_factor"] or 0) >= 1.3 and
                    m["robustness"] >= .3 and m["score"] >= 40)
        ranked.append((eligible, m["robustness"] * np.sign(m["score"]),
                       m["profit_factor"] or 0, params))
    eligible_ranked = [x for x in ranked if x[0]]
    selected = max(eligible_ranked or ranked, key=lambda x: (x[1], x[2]))[3]
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
               "parameter_evaluation": {"full_grid_size": 2916,
                 "staged": staged, "screened_range_filters": 27 if staged else None,
                 "expanded_exit_combinations": len(candidates),
                 "eligible_development_validation_candidates": len(eligible_ranked)},
               "selected_parameters": selected, "fold_boundaries": {p: {s: [str(x.index.min()), str(x.index.max())] for s, x in fs.items()} for p, fs in folds.items()},
               "pair_results": pair_results, "aggregate_cross_pair_test": agg,
               "cost_stress": stress, "randomized_control": controls,
               "controls": {"no_trade": {"scope": "full_historical_diagnostic", "return": 0.0},
                            "random_session_direction": "20 deterministic seeds above",
                            "random_breakout_time": "reserved deterministic randomized-control family",
                            "previous_day_high_low": "full_historical_diagnostic",
                            "existing_d1_london_approximation": "full_historical_diagnostic",
                            "buy_and_hold": "diagnostic only"},
               "acceptance": acceptance,
               "classification": ("3 FORWARD-VALIDATION CANDIDATE" if all(acceptance.values())
                                  else "1 REJECT STRATEGY FAMILY")}
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
        checked = {pair: verify_input(pair, args.data_dir) for pair in CORE_PAIRS}
        frames = {pair: checked[pair][0] for pair in CORE_PAIRS}
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    findings = {pair: checked[pair][1] for pair in CORE_PAIRS}
    RESULTS.mkdir(exist_ok=True)
    for pair, finding in findings.items():
        (RESULTS / f"session_breakout_integrity_{pair}.json").write_text(
            json.dumps(finding, indent=2, sort_keys=True) + "\n")
        (RESULTS / f"session_breakout_integrity_{pair}.md").write_text(
            f"# {pair} H1 integrity\n\nRaw SHA-256: `{finding['raw_sha256']}`. "
            f"Evaluated SHA-256: `{finding['evaluated_sha256']}`. Raw/evaluated rows: "
            f"{finding['raw_rows']}/{finding['evaluated_rows']}; evaluated through "
            f"{finding['evaluated_end']}. Invalid OHLC: {finding['invalid_ohlc']}; duplicates: "
            f"{finding['duplicate_timestamps']}; negative volume: {finding['negative_volume']}; "
            f"unexpected long gaps: {len(finding['unexpected_long_gaps'])}.\n")
    payload = research(frames, persist=False)
    payload["inputs"] = findings
    (RESULTS / "session_breakout_phase1.json").write_text(
        json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
