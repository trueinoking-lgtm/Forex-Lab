"""Accounting invariants for the frozen range-MR reconciliation."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run_range_mean_reversion_research as recon
from src.canonical_eval import gate_outcomes


@pytest.fixture(scope="module")
def report():
    recon.main()
    path = Path(recon.RESULTS) / "range_mr_fold_results.json"
    return json.loads(path.read_text())


def test_range_subset_is_same_closed_ledger_when_no_outside_trades(report):
    full = report["results"]["full_historical_diagnostic"]
    range_only = report["results"]["regime_range"]
    trend = report["results"]["regime_trend"]
    assert trend["trade_count"] == 0
    assert range_only["completed_trade_ids"] == full["completed_trade_ids"]
    assert range_only["lifecycle_profit_factor"] == full["lifecycle_profit_factor"]


def test_canonical_three_bps_equals_three_bps_stress(report):
    canonical = report["results"]["full_historical_diagnostic"]
    stress = report["cost_stress"]["3bps"]
    for key in ("completed_trade_ids", "gross_profit", "gross_loss",
                "lifecycle_profit_factor"):
        assert stress[key] == canonical[key]
    assert stress["cost_assumptions"] == canonical["cost_assumptions"]


def test_nonpositive_return_can_never_report_all_gates_passed():
    gates = gate_outcomes({"score": 100, "robustness": 1, "oos_return": 0,
                           "profit_factor": 10})
    assert gates["oos_return_gt_0"] is False
    assert all(gates.values()) is False


def test_same_closed_trade_ids_always_produce_same_pf(report):
    full = report["results"]["full_historical_diagnostic"]
    range_only = report["results"]["regime_range"]
    assert full["completed_trade_ids"] == range_only["completed_trade_ids"]
    first = full["gross_profit"] / full["gross_loss"]
    second = range_only["gross_profit"] / range_only["gross_loss"]
    assert first == second == full["lifecycle_profit_factor"]


def test_aggregate_pf_is_recomputed_not_fold_pf_average(report):
    aggregate = report["results"]["aggregate_walk_forward_test"]
    folds = report["chronological_test_folds"]
    expected = sum(f["gross_profit"] for f in folds) / sum(f["gross_loss"] for f in folds)
    fold_pfs = [f["lifecycle_profit_factor"] for f in folds
                if f["lifecycle_profit_factor"] is not None]
    assert aggregate["lifecycle_profit_factor"] == pytest.approx(expected)
    assert aggregate["lifecycle_profit_factor"] != pytest.approx(sum(fold_pfs) / len(fold_pfs))
