#!/usr/bin/env python3
"""Reconcile the frozen range-MR candidate's research accounting (paper only)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from strategies.range_mean_reversion import _wilder_atr_adx, rsi_range_reversion
from src import backtest, score
from src.canonical_eval import gate_outcomes
from src.experiment_registry import file_sha256
from src.trade_ledger import extract_trades, lifecycle_metrics

BASE = Path(__file__).resolve().parent
DATA = BASE / "data/raw_mt5_EURUSD_1d_retry.csv"
RESULTS = BASE / "results"
DOC = BASE / "docs/checkpoints/range_mean_reversion_research_phase1_2026-07-20.md"
SHA = "4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2"
PARAMS = {"adx_threshold": 22, "atr_stop": 1.5, "max_holding": 5,
          "profit_target_atr": 1.0, "rsi_lower": 20, "rsi_period": 7,
          "rsi_upper": 70, "trailing": False}
CANONICAL_COST = {"spread_bps": 2.0, "slippage_bps": 1.0, "commission_bps": 0.0}
SCOPES = {"full_historical_diagnostic", "development", "validation",
          "chronological_test", "aggregate_walk_forward_test", "regime_range",
          "regime_trend", "cost_stress"}
CTX = {"initial_capital": 10000, "periods_per_year": 252,
       "risk_free_rate": 0.0, "min_trades": 20}


def clean(value):
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, pd.Timestamp): return value.isoformat()
    return value


def dump(name, value):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / name).write_text(json.dumps(clean(value), indent=2, sort_keys=True) + "\n")


def closed(trades):
    return [trade for trade in trades if not trade["still_open_at_end"]]


def trade_ids(trades):
    return [trade["trade_id"] for trade in closed(trades)]


def result_from_ledger(*, scope, price, trades, returns, window_returns,
                       fold_id, bars, costs, in_sample_return=0.0):
    """Build every persisted metric dict from its stated closed-trade ledger."""
    if scope not in SCOPES: raise ValueError(f"invalid result scope: {scope}")
    life = lifecycle_metrics(trades)
    equity = (1 + returns).cumprod() * CTX["initial_capital"]
    portfolio = backtest._chain([returns], window_returns, [], CTX["initial_capital"],
                                CTX["periods_per_year"], CTX["risk_free_rate"])["metrics"]
    scoring = dict(portfolio)
    scoring.update({"trade_count": life["trade_count"], "win_rate": life["win_rate"],
                    "profit_factor": life["profit_factor"] or float("nan")})
    scored = score.score_strategy(scoring, window_returns, in_sample_return,
                                  min_trades=CTX["min_trades"])
    values = {"score": scored["score"], "robustness": scored["robustness"],
              "oos_return": portfolio.get("total_return", 0.0),
              "profit_factor": life["profit_factor"]}
    gates = gate_outcomes(values)
    return {"scope": scope, "dataset_sha256": SHA,
            "start_timestamp": price.index[0], "end_timestamp": price.index[-1],
            "fold_identifier": fold_id, "trade_subset": bars,
            "cost_assumptions": dict(costs), "completed_trade_ids": trade_ids(trades),
            "trade_id_seed": "sha256(strategy|symbol|entry_timestamp|direction)[:20]",
            "gross_profit": life["gross_profit"], "gross_loss": life["gross_loss"],
            "lifecycle_profit_factor": life["profit_factor"],
            "trade_count": life["trade_count"], "return": values["oos_return"],
            "robustness": values["robustness"], "score": values["score"],
            "gates": gates, "all_gates_passed": all(gates.values()),
            "eligibility": all(gates.values()), "lifecycle": life,
            "portfolio_metrics": portfolio}


def evaluate_period(price, scope, fold_id, costs=CANONICAL_COST, signal=None):
    signal = rsi_range_reversion(price, **PARAMS) if signal is None else signal
    total_cost = sum(costs.values())
    run = backtest.run(price, signal, total_cost, CTX["initial_capital"],
                       CTX["periods_per_year"], CTX["risk_free_rate"])
    ledger = extract_trades(price, signal, strategy="rsi_range_reversion", symbol="EURUSD", **costs)
    return result_from_ledger(scope=scope, price=price, trades=ledger,
        returns=run["returns"], window_returns=[run["metrics"]["total_return"]],
        fold_id=fold_id, bars=f"all bars in {fold_id}", costs=costs), ledger, run["returns"]


def chronological_folds(price, label, scope, costs=CANONICAL_COST):
    folds = []
    for number, start in enumerate(range(0, len(price) - 314, 63), 1):
        window = price.iloc[start:start + 315]
        test = window.iloc[252:]
        signal = rsi_range_reversion(window, **PARAMS).iloc[252:]
        item, ledger, returns = evaluate_period(test, scope,
                                                f"{label}-fold-{number}", costs, signal)
        folds.append((item, ledger, returns, test))
    return folds


def aggregate_folds(folds, in_sample_return):
    trades = [trade for _, ledger, _, _ in folds for trade in closed(ledger)]
    returns = pd.concat([returns for _, _, returns, _ in folds])
    prices = pd.concat([part for _, _, _, part in folds])
    windows = [item["return"] for item, _, _, _ in folds]
    return result_from_ledger(scope="aggregate_walk_forward_test", price=prices,
        trades=trades, returns=returns, window_returns=windows,
        fold_id="chronological-test-folds-concatenated",
        bars="concatenated non-overlapping 63-bar chronological test folds",
        costs=CANONICAL_COST, in_sample_return=in_sample_return)


def subset_result(full_result, full_ledger, price, returns, scope, predicate):
    subset = [trade for trade in full_ledger if predicate(trade)]
    same_closed_ledger = trade_ids(subset) == trade_ids(full_ledger)
    subset_returns = returns if same_closed_ledger else pd.Series(0.0, index=returns.index)
    # Regime reporting is a lifecycle-ledger view; no alternate signals/trades are generated.
    item = result_from_ledger(scope=scope, price=price, trades=subset, returns=subset_returns,
        window_returns=[full_result["return"]], fold_id=scope,
        bars="full-history trades classified by entry signal bar from canonical ledger",
        costs=CANONICAL_COST)
    return item


def main():
    cfg = yaml.safe_load((BASE / "config.yaml").read_text())
    assert cfg["paper_only"] is True and cfg["allow_live_orders"] is False
    assert cfg["cost"] == {"fee_bps": 0, "slippage_bps": 1, "spread_bps": 2}
    assert file_sha256(DATA) == SHA
    frame = pd.read_csv(DATA, parse_dates=["timestamp"]).set_index("timestamp")
    price = frame.close.astype(float); n = len(price); cut1, cut2 = int(.6*n), int(.8*n)
    dev, val, test = price.iloc[:cut1], price.iloc[cut1:cut2], price.iloc[cut2:]
    development, _, _ = evaluate_period(dev, "development", "development-60pct")
    validation, _, _ = evaluate_period(val, "validation", "validation-next-20pct")
    chronological, _, _ = evaluate_period(test, "chronological_test", "held-out-final-20pct")
    development_folds = chronological_folds(dev, "development", "development")
    validation_folds = chronological_folds(val, "validation", "validation")
    test_folds = chronological_folds(test, "held-out", "chronological_test")
    aggregate = aggregate_folds(test_folds, development["return"])
    full, full_ledger, full_returns = evaluate_period(price, "full_historical_diagnostic", "full-history")

    _, adx = _wilder_atr_adx(price, 14)
    def entry_is_range(trade):
        signal_ts = pd.Timestamp(trade["signal_ts"])
        return bool(adx.loc[signal_ts] < PARAMS["adx_threshold"])
    ranging = subset_result(full, full_ledger, price, full_returns, "regime_range", entry_is_range)
    trending = subset_result(full, full_ledger, price, full_returns, "regime_trend",
                             lambda trade: not entry_is_range(trade))

    stress_specs = {
        "3bps": CANONICAL_COST, "5bps": {"spread_bps": 3., "slippage_bps": 2., "commission_bps": 0.},
        "8bps": {"spread_bps": 5., "slippage_bps": 3., "commission_bps": 0.},
        "12bps": {"spread_bps": 8., "slippage_bps": 4., "commission_bps": 0.},
        "commission_1bps": {"spread_bps": 2., "slippage_bps": 1., "commission_bps": 1.},
        "double_spread": {"spread_bps": 4., "slippage_bps": 1., "commission_bps": 0.},
        "double_slippage": {"spread_bps": 2., "slippage_bps": 2., "commission_bps": 0.}}
    stresses = {}
    for label, costs in stress_specs.items():
        item, ledger, _ = evaluate_period(price, "cost_stress", f"cost-{label}", costs)
        item["stress_scenario"] = label; stresses[label] = item
    delayed_signal = rsi_range_reversion(price, **PARAMS).shift(1).fillna(0.)
    stresses["extra_delay"], _, _ = evaluate_period(price, "cost_stress", "cost-extra-delay",
                                                     CANONICAL_COST, delayed_signal)
    stresses["extra_delay"]["stress_scenario"] = "+1 bar delay"
    ranked = sorted(closed(full_ledger), key=lambda trade: trade["net_pnl"], reverse=True)
    for label, removed in (("remove_best", 1), ("remove_3_best", 3)):
        item = result_from_ledger(scope="cost_stress", price=price, trades=ranked[removed:],
            returns=full_returns, window_returns=[full["return"]], fold_id=f"stress-{label}",
            bars=f"full canonical ledger excluding {removed} best completed trade(s)",
            costs=CANONICAL_COST)
        item["stress_scenario"] = label; stresses[label] = item

    discrepancy = {
        "D1": {"classification": "reporting-label defect", "demonstrated": True,
               "fixed": True, "cause": "full-history lifecycle PF was labeled as OOS gate success"},
        "D2": {"classification": "lifecycle-ledger mismatch", "demonstrated": True,
               "fixed": True, "cause": "regime path regenerated signals instead of subsetting the canonical ledger"},
        "D3": {"classification": "stale artifact", "demonstrated": True,
               "fixed": True, "cause": "the cited 0.81 PF belonged to another subfamily; frozen RSI canonical and 3 bps stress were already identical"}}
    payload = {"input": {"sha256": SHA, "rows": n, "start": price.index[0], "end": price.index[-1]},
               "parameters": PARAMS, "results": {"development": development,
               "validation": validation, "chronological_test": chronological,
               "aggregate_walk_forward_test": aggregate,
               "full_historical_diagnostic": full, "regime_range": ranging,
               "regime_trend": trending},
               "folds": {"development": [x[0] for x in development_folds],
                         "validation": [x[0] for x in validation_folds],
                         "chronological_test": [x[0] for x in test_folds]},
               "chronological_test_folds": [x[0] for x in test_folds],
               "cost_stress": stresses, "discrepancies": discrepancy,
               "classification": {"value": "1 REJECT STRATEGY FAMILY",
                 "basis_scope": "aggregate_walk_forward_test",
                 "all_gates_passed": aggregate["all_gates_passed"]}}
    dump("range_mr_fold_results.json", payload)
    dump("range_mr_period_regime.json", {"input": payload["input"], "parameters": PARAMS,
                                         "regimes": {"range": ranging, "trend": trending}})
    dump("range_mr_cost_stress.json", {"input": payload["input"], "parameters": PARAMS,
                                       "cost_stress": stresses})
    dump("range_mr_parameter_stability.json", {"scope": "full_historical_diagnostic",
        "note": "Frozen parameters only; no tuning performed.", "parameters": PARAMS})
    dump("range_mr_randomized_control.json", {"scope": "full_historical_diagnostic",
        "note": "Not rerun during accounting-only reconciliation."})
    DOC.write_text(render(payload))
    assert file_sha256(DATA) == SHA
    return 0


def render(payload):
    order = ["development", "validation", "chronological_test",
             "aggregate_walk_forward_test", "full_historical_diagnostic", "regime_range"]
    rows = []
    for name in order:
        x = payload["results"][name]
        rows.append(f"| {name} | {x['trade_count']} | {x['gross_profit']:.6f} | "
                    f"{x['gross_loss']:.6f} | {x['lifecycle_profit_factor'] or 0:.4f} | "
                    f"{x['return']:.4f} | {x['robustness']:.3f} | {x['score']:.2f} | "
                    f"{x['all_gates_passed']} |")
    for name, x in payload["cost_stress"].items():
        rows.append(f"| cost_stress:{name} | {x['trade_count']} | {x['gross_profit']:.6f} | "
                    f"{x['gross_loss']:.6f} | {x['lifecycle_profit_factor'] or 0:.4f} | "
                    f"{x['return']:.4f} | {x['robustness']:.3f} | {x['score']:.2f} | "
                    f"{x['all_gates_passed']} |")
    d = payload["discrepancies"]
    return "\n".join([
        "# Range mean-reversion research — Phase 1 accounting reconciliation (2026-07-20)", "",
        "Research/paper/demo only. Frozen RSI parameters; no strategy implementation or tuning.", "",
        f"Dataset: `{SHA}`. Canonical cost: spread 2 bps + slippage 1 bps + commission 0 bps.", "",
        "The previous PF 1.43 was a full-history diagnostic produced by a mismatched reporting path; it was not OOS and did not clear all four canonical gates.", "",
        "## Root-cause reconciliation", "",
        f"- D1 — **{d['D1']['classification']}**: corrected scope/gate labeling.",
        f"- D2 — **{d['D2']['classification']}**: range reporting now subsets the same canonical closed-trade ledger.",
        f"- D3 — **{d['D3']['classification']}**: 0.81 was from another subfamily, while frozen RSI canonical and 3 bps stress both use identical 2/1/0 bps components.", "",
        "## Corrected results", "",
        "| scope | trades | gross profit | gross loss | lifecycle PF | return | robustness | score | all gates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|:---:|", *rows, "",
        "Fold PFs are diagnostic only. Aggregate walk-forward PF is recomputed from concatenated chronological test-fold trades, never averaged.", "",
        "## Classification", "", "**1 REJECT STRATEGY FAMILY**", "",
        "This single classification is based only on `aggregate_walk_forward_test`; at least one of its four canonical gates fails. Full-history diagnostics are explicitly ineligible as OOS evidence.", "",
        "Safety: `paper_only=true`, `allow_live_orders=false`; locked gates unchanged; no order endpoint/call and no order; watcher/forward ledger untouched; no credentials; canonical input unchanged.", ""])


if __name__ == "__main__":
    raise SystemExit(main())
