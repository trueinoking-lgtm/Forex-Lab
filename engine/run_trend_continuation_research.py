#!/usr/bin/env python3
"""Deterministic, research-only Phase 1 trend-continuation evaluation."""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from strategies.registry import REGISTRY, ema_crossover
from strategies.trend_continuation import _wilder_atr_adx, trend_continuation
from src import backtest
from src.baseline import buy_and_hold, circular_shift, no_trade, sma_crossover
from src.canonical_eval import evaluate_strategy_canonical
from src.experiment_registry import file_sha256, git_commit, register_experiment
from src.trade_ledger import extract_trades, lifecycle_metrics


BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "raw_mt5_EURUSD_1d_retry.csv"
EXPECTED_SHA = "4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2"
RESULTS = BASE / "results"
DOC = BASE / "docs" / "checkpoints" / "trend_continuation_research_phase1_2026-07-20.md"
WF = {"train_days": 252, "test_days": 63, "step_days": 63}
STANDARD_COMPONENTS = {"spread_bps": 1.0, "slippage_bps": 1.0, "commission_bps": 1.0}


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")


def context(cost_bps: float = 3.0) -> dict:
    return {"walk_forward": dict(WF), "cost_bps": cost_bps, "initial_capital": 10000,
            "periods_per_year": 252, "risk_free_rate": 0.0, "min_trades": 20}


def load_price() -> pd.Series:
    if file_sha256(DATA) != EXPECTED_SHA:
        raise SystemExit("canonical input hash mismatch; refusing research run")
    frame = pd.read_csv(DATA, parse_dates=["timestamp"]).set_index("timestamp")
    return frame["close"].astype(float).sort_index()


def parameter_grid() -> list[dict]:
    pairs = ((8, 40), (8, 150), (12, 60), (12, 100),
             (20, 60), (20, 150), (30, 40), (30, 150))
    rows = []
    for (fast, slow), adx, atr, low, stop, trailing in itertools.product(
            pairs, (18, 30), (14, 20), (20, 30), (1.5, None), (False, True)):
        rows.append({"fast": fast, "slow": slow, "adx_threshold": adx,
                     "atr_lookback": atr, "vol_lookback": 20, "vol_low_pct": low,
                     "vol_high_pct": 90, "stop_atr": stop, "trailing": trailing})
    return rows


def canonical(price: pd.Series, fn, name: str, params: dict | None = None,
              *, ctx: dict | None = None, components: dict | None = None) -> dict:
    comp = components or STANDARD_COMPONENTS
    return evaluate_strategy_canonical(
        price, fn, ctx or context(), strategy=name, symbol="EURUSD", params=params or {}, **comp)


def compact(result: dict, price: pd.Series, fn, params: dict) -> dict:
    signal = fn(price, **params)
    exposure = float(signal.shift(1).fillna(0).ne(0).mean())
    life = dict(result["lifecycle_metrics"])
    closed = [t for t in result["trades"] if not t["still_open_at_end"]]
    wins = sorted((max(0.0, float(t["net_pnl"])) for t in closed), reverse=True)
    gross_profit = sum(wins)
    life["best_3_gross_profit_pct"] = sum(wins[:3]) / gross_profit if gross_profit else 0.0
    life["avg_holding_bars"] = life.pop("avg_holding_time")
    for side in ("long", "short"):
        side_life = lifecycle_metrics([t for t in result["trades"] if t["direction"] == side])
        side_life["avg_holding_bars"] = side_life.pop("avg_holding_time")
        life[f"{side}_side"] = side_life
    return clean({"lifecycle": life, "total_return": result["oos_return"],
                  "max_drawdown": result["portfolio_metrics"].get("max_drawdown"),
                  "exposure": exposure, "robustness": result["robustness"],
                  "score": result["score"], "gates": result["gates"],
                  "eligible": result["eligible"], "rejection_reasons": result["rejection_reasons"]})


def folds(price: pd.Series, params: dict) -> list[dict]:
    out = []
    start = 0
    while start + WF["train_days"] + WF["test_days"] <= len(price):
        observed = price.iloc[start:start + WF["train_days"] + WF["test_days"]]
        signal = trend_continuation(observed, **params)
        test_price = observed.iloc[WF["train_days"]:]
        test_signal = signal.iloc[WF["train_days"]:]
        run = backtest.run(test_price, test_signal, 3, 10000, 252, 0)
        trades = extract_trades(test_price, test_signal, strategy="trend_continuation",
                                symbol="EURUSD", **STANDARD_COMPONENTS)
        out.append(clean({"fold": len(out) + 1, "start": test_price.index[0],
                          "end": test_price.index[-1], "portfolio": run["metrics"],
                          "lifecycle": lifecycle_metrics(trades)}))
        start += WF["step_days"]
    return out


def neighbor_params(selected: dict) -> list[dict]:
    axes = {"fast": (8, 12, 20, 30), "slow": (40, 60, 100, 150),
            "adx_threshold": (18, 22, 25, 30), "atr_lookback": (14, 20),
            "vol_low_pct": (20, 30), "stop_atr": (1.5, 2.0, 2.5, None),
            "trailing": (False, True)}
    neighbors = [dict(selected)]
    for key, values in axes.items():
        at = values.index(selected[key])
        for nxt in (at - 1, at + 1):
            if 0 <= nxt < len(values):
                candidate = {**selected, key: values[nxt]}
                if candidate["fast"] < candidate["slow"]:
                    neighbors.append(candidate)
    unique = {json.dumps(row, sort_keys=True): row for row in neighbors}
    return list(unique.values())


def annual_concentration(price: pd.Series, params: dict) -> float:
    result = backtest.run(price, trend_continuation(price, **params), 3, 10000, 252, 0)
    annual = result["returns"].groupby(result["returns"].index.year).apply(lambda x: (1 + x).prod() - 1)
    positive = annual.clip(lower=0)
    return float(positive.max() / positive.sum()) if positive.sum() else 1.0


def markdown(report: dict) -> str:
    s = report["selected_candidate"]
    lines = ["# Trend-continuation research — Phase 1 (2026-07-20)", "",
             "Research/paper/demo only. No order endpoint was called and no order was placed.", "",
             "## Protocol and selection", "",
             f"Canonical input: `{report['input']['rows']}` bars, `{report['input']['start']}` through `{report['input']['end']}`; SHA-256 verified.",
             f"The deliberate coarse subset contains **{report['grid']['evaluated_count']}** candidates ({report['grid']['coverage']}).",
             "Chronological partitions are earliest 60% development, middle 20% validation, latest 20% held-out test. Each partition uses the existing 252/63/63 walk-forward engine.",
             "Selection requires all four locked canonical gates on validation, then ranks by `robustness * sign(score)`, lifecycle PF, and deterministic parameter JSON; return is not a ranking key. If none passes, the family is rejected and the top diagnostic candidate is reported without promotion.", "",
             "## Selected diagnostic candidate", "", f"Parameters: `{json.dumps(s['parameters'], sort_keys=True)}`", "",
             f"Validation gates passed: **{s['validation_gate_pass']}**. Classification: **{report['classification']}**.", "",
             "### Per-fold lifecycle metrics", "",
             "| Partition/fold | Dates | Trades | W/L | PF | Expectancy | Avg hold | Return | Max DD |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for part, rows in report["walk_forward_folds"].items():
        for row in rows:
            life, port = row["lifecycle"], row["portfolio"]
            lines.append(f"| {part}/{row['fold']} | {row['start'][:10]}..{row['end'][:10]} | {life['trade_count']} | {life['wins']}/{life['losses']} | {life['profit_factor']} | {life['expectancy']:.6f} | {life['avg_holding_time']:.1f} | {port['total_return']:.4f} | {port['max_drawdown']:.4f} |")
    lines += ["", "## Aggregate and frozen baselines", "", "| Strategy | Trades | W/L | PF | Expectancy | Return | Max DD | Exposure | Robustness | Score | Best/Best-3 GP | Gates |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for name, row in report["aggregate_vs_baselines"].items():
        life = row["lifecycle"]
        lines.append(f"| {name} | {life['trade_count']} | {life['wins']}/{life['losses']} | {life['profit_factor']} | {life['expectancy']:.6f} | {row['total_return']:.4f} | {row['max_drawdown']:.4f} | {row['exposure']:.3f} | {row['robustness']} | {row['score']} | {life['largest_trade_gross_profit_pct']:.3f}/{life['best_3_gross_profit_pct']:.3f} | {row['gates']} |")
    selected_life = report["aggregate_vs_baselines"]["trend_continuation"]["lifecycle"]
    lines += ["", "Selected long-side lifecycle: `" + str(selected_life["long_side"]) + "`",
              "", "Selected short-side lifecycle: `" + str(selected_life["short_side"]) + "`",
              "", "## Stability, regimes, and cost stress", "", f"Nearby stability: `{report['stability_summary']}`", "", f"Regime results: `{report['regime_results']}`", "", "| Scenario | PF | Return | Max DD |", "|---|---:|---:|---:|"]
    for name, row in report["cost_stress"].items():
        lines.append(f"| {name} | {row['profit_factor']} | {row['return']} | {row['max_drawdown']} |")
    lines += ["", "## Rejection rules and classification", ""]
    lines += [f"- {name}: **{'PASS' if passed else 'FAIL'}**" for name, passed in report["rejection_rule_results"].items()]
    lines += ["", f"Final classification: **{report['classification']}**. " + report["classification_rationale"], "",
              "Safety confirmation: `paper_only=true`, `allow_live_orders=false`, and locked gates are unchanged. Watcher, cron, bridge, filling, zero-spread, retcodes, signal timestamps, execution code, and the forward-validation ledger were untouched. The canonical dataset and all other inputs were untouched.", ""]
    return "\n".join(lines)


def main() -> int:
    cfg = yaml.safe_load((BASE / "config.yaml").read_text())
    if not cfg.get("paper_only") or cfg.get("allow_live_orders"):
        raise SystemExit("safety rails require paper_only=true and allow_live_orders=false")
    price = load_price()
    n = len(price)
    dev, validation, test = price.iloc[:int(n * .6)], price.iloc[int(n * .6):int(n * .8)], price.iloc[int(n * .8):]
    grid = parameter_grid()
    screened = []
    for params in grid:
        dev_result = canonical(dev, trend_continuation, "trend_continuation", params)
        val_result = canonical(validation, trend_continuation, "trend_continuation", params)
        screened.append((params, dev_result, val_result))
    passing = [row for row in screened if row[2]["eligible"]]
    pool = passing or screened
    pool.sort(key=lambda row: (row[2]["robustness"] * (1 if row[2]["score"] > 0 else -1),
                               row[2]["profit_factor"] or -1, json.dumps(row[0], sort_keys=True)), reverse=True)
    params, dev_result, val_result = pool[0]
    test_result = canonical(test, trend_continuation, "trend_continuation", params)
    full_result = canonical(price, trend_continuation, "trend_continuation", params)

    definitions = {
        "trend_continuation": (trend_continuation, params),
        "ema_crossover": (ema_crossover, {"fast": 12, "slow": 26}),
        "simple_ma_crossover": (sma_crossover, {"fast": 20, "slow": 50}),
        "buy_and_hold": (buy_and_hold, {}), "no_trade": (no_trade, {}),
        "fixed_seed_randomized_entry": (lambda p: circular_shift(ema_crossover(p), 7), {}),
    }
    aggregates = {}
    for name, (fn, kw) in definitions.items():
        result = canonical(price, fn, name, kw)
        aggregates[name] = compact(result, price, fn, kw)

    stability_rows = []
    for neighbor in neighbor_params(params):
        result = canonical(price, trend_continuation, "trend_continuation", neighbor)
        stability_rows.append({"parameters": neighbor, "profit_factor": result["profit_factor"],
                               "return": result["oos_return"], "robustness": result["robustness"],
                               "score": result["score"]})
    selected_pf = full_result["profit_factor"] or 0.0
    neighbor_only = [r for r in stability_rows if r["parameters"] != params]
    finite_pf = [r["profit_factor"] for r in neighbor_only if r["profit_factor"] is not None]
    stability_pass = bool(finite_pf and np.median(finite_pf) >= .8 * selected_pf and
                          np.median([r["return"] for r in neighbor_only]) > 0)

    _, regime_adx = _wilder_atr_adx(price, 14)
    regime_results = {}
    for label, mask in (("trend", regime_adx >= 25), ("range", regime_adx < 20)):
        fn = lambda p, m=mask: trend_continuation(p, **params).where(m.reindex(p.index).fillna(False), 0.0)
        rr = canonical(price, fn, f"trend_continuation_{label}")
        regime_results[label] = compact(rr, price, fn, {})

    stresses = {
        "3bps_standard": (context(3), STANDARD_COMPONENTS, trend_continuation),
        "5bps_total": (context(5), {"spread_bps": 2, "slippage_bps": 2, "commission_bps": 1}, trend_continuation),
        "8bps_total": (context(8), {"spread_bps": 3.5, "slippage_bps": 3.5, "commission_bps": 1}, trend_continuation),
        "12bps_total": (context(12), {"spread_bps": 5.5, "slippage_bps": 5.5, "commission_bps": 1}, trend_continuation),
        "doubled_spread": (context(4), {"spread_bps": 2, "slippage_bps": 1, "commission_bps": 1}, trend_continuation),
        "doubled_slippage": (context(4), {"spread_bps": 1, "slippage_bps": 2, "commission_bps": 1}, trend_continuation),
        "extra_execution_bar": (context(3), STANDARD_COMPONENTS,
                                lambda p, **kw: trend_continuation(p, **kw).shift(1).fillna(0)),
    }
    cost_stress = {}
    for name, (ctx, comp, fn) in stresses.items():
        row = canonical(price, fn, "trend_continuation", params, ctx=ctx, components=comp)
        cost_stress[name] = clean({"profit_factor": row["profit_factor"], "return": row["oos_return"],
                                   "max_drawdown": row["portfolio_metrics"].get("max_drawdown")})

    life = full_result["lifecycle_metrics"]
    simple = aggregates["simple_ma_crossover"]
    annual_share = annual_concentration(price, params)
    trend_return = regime_results["trend"]["total_return"] or 0
    range_return = regime_results["range"]["total_return"] or 0
    regime_primary = abs(trend_return) > 4 * max(abs(range_return), .001)
    rules = {
        "lifecycle_pf_gte_1_3": (life["profit_factor"] or 0) >= 1.3,
        "walk_forward_return_gt_0": full_result["oos_return"] > 0,
        "robustness_gte_0_3": full_result["robustness"] >= .3,
        "score_gte_40": full_result["score"] >= 40,
        "closed_trades_gte_100": life["trade_count"] >= 100,
        "largest_trade_lte_20pct_gross_profit": life["largest_trade_gross_profit_pct"] <= .2,
        "not_one_short_period_or_regime": annual_share <= .5 and not regime_primary,
        "nearby_parameters_do_not_collapse": stability_pass,
        "reasonable_cost_stress": all((row["return"] or -1) > 0 and (row["profit_factor"] or 0) >= 1.0 for row in cost_stress.values()),
        "not_materially_below_simple_ma": full_result["oos_return"] >= .8 * simple["total_return"] and (life["profit_factor"] or 0) >= .8 * (simple["lifecycle"]["profit_factor"] or 0),
    }
    classification = "2 CONTINUE RESEARCH" if passing and all(rules.values()) else "1 REJECT STRATEGY FAMILY"
    rationale = ("All Phase 1 promotion rules passed." if classification.startswith("2") else
                 "At least one non-negotiable rejection rule failed; no candidate is promoted.")
    report = clean({
        "schema_version": 1, "research_only": True,
        "input": {"path": str(DATA.relative_to(BASE)), "sha256": EXPECTED_SHA, "rows": n,
                  "start": price.index[0], "end": price.index[-1]},
        "grid": {"evaluated_count": len(grid), "coverage": "8 fast/slow extreme-spanning pairs x 2 ADX x 2 ATR x 2 vol floors x 2 stop extremes x 2 trailing; vol lookback 20 and ceiling 90 fixed"},
        "selection_rule": "validation must pass all locked canonical gates; rank by robustness*sign(score), then lifecycle PF, then deterministic parameter JSON; never rank by return",
        "partition_rows": {"development": len(dev), "validation": len(validation), "test": len(test)},
        "selected_candidate": {"parameters": params, "validation_gate_pass": bool(passing),
                               "development": compact(dev_result, dev, trend_continuation, params),
                               "validation": compact(val_result, validation, trend_continuation, params),
                               "held_out_test": compact(test_result, test, trend_continuation, params)},
        "walk_forward_folds": {"development": folds(dev, params), "validation": folds(validation, params),
                               "held_out_test": folds(test, params)},
        "aggregate_vs_baselines": aggregates, "nearby_parameter_results": stability_rows,
        "stability_summary": {"neighbor_count": len(neighbor_only), "median_neighbor_pf": np.median(finite_pf) if finite_pf else None,
                              "median_neighbor_return": np.median([r["return"] for r in neighbor_only]), "pass": stability_pass},
        "regime_results": regime_results, "cost_stress": cost_stress,
        "period_concentration": {"largest_positive_year_share": annual_share, "regime_primary": regime_primary},
        "rejection_rule_results": rules, "classification": classification,
        "classification_rationale": rationale, "safety": {"paper_only": True, "allow_live_orders": False,
        "gates_unchanged": True, "orders_placed": 0, "inputs_untouched": True}})
    write_json(RESULTS / "trend_continuation_walkforward.json", report)
    write_json(RESULTS / "parameter_stability.json", {"selected": params, "results": stability_rows,
                                                        "summary": report["stability_summary"]})
    write_json(RESULTS / "cost_stress.json", {"selected": params, "scenarios": cost_stress})
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(markdown(report))

    registry_metrics = {"total_return": full_result["portfolio_metrics"].get("total_return"),
                        "max_drawdown": full_result["portfolio_metrics"].get("max_drawdown"),
                        "profit_factor": full_result["profit_factor"], "win_rate": life["win_rate"],
                        "trade_count": life["trade_count"], "score": full_result["score"],
                        "robustness": full_result["robustness"], "oos_return": full_result["oos_return"]}
    register_experiment({"strategy_name": "trend_continuation", "symbol": "EURUSD", "timeframe": "1d",
                         "git_commit_hash": git_commit(BASE.parent), "data_sha256": EXPECTED_SHA,
                         "parameters": params, "performance_metrics": registry_metrics,
                         "final_status": "rejected" if classification.startswith("1") else "research_candidate",
                         "rejection_reasons": [name for name, passed in rules.items() if not passed],
                         "artifacts": ["trend_continuation_walkforward.json", "parameter_stability.json", "cost_stress.json"]},
                        RESULTS / "experiment_registry.json", RESULTS / "experiment_registry.md",
                        created_at="2026-07-20T00:00:00Z")
    print(json.dumps({"classification": classification, "parameters": params,
                      "validation_passers": len(passing), "rules": rules}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
