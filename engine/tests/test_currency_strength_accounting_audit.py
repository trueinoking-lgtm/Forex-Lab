import json
from pathlib import Path

import pytest

from run_currency_strength_research import (
    FROZEN_CONFIG,
    currency_boundary_passes,
    frozen_config_hash,
    gates,
    metrics,
    portfolio_equity,
    rank_selection_inputs,
    run_audit,
)


RESULTS = Path(__file__).parents[1] / "results"


def trade(trade_id, pnl, hour):
    return {"trade_id":trade_id,"net_pnl_usd":pnl,"pair":"EURUSD",
            "direction":"long","holding_hours":1,
            "entry_timestamp":f"2025-01-01T{hour-1:02d}:00:00+00:00",
            "exit_timestamp":f"2025-01-01T{hour:02d}:00:00+00:00"}


def test_floored_equity_bankruptcy_invariants_and_no_later_trade():
    ledger=[trade("a",100,1),trade("b",-20_000,2),trade("c",500,3)]
    result=portfolio_equity(ledger)
    assert all(row["equity"] >= 0 for row in result["equity_curve"])
    assert 0 <= result["max_drawdown_decimal"] <= 1
    assert result["bankrupt"] and result["portfolio_return_decimal"] == -1.0
    assert [t["trade_id"] for t in result["accepted_trades"]] == ["a","b"]
    assert [t["trade_id"] for t in result["rejected_trades"]] == ["c"]
    assert result["final_trade_before_bankruptcy"]["exit_timestamp"] < ledger[2]["exit_timestamp"]
    assert result["portfolio_return_decimal"] == result["ending_equity"] / result["starting_equity"] - 1


def test_arithmetic_diagnostic_is_separate_and_cannot_drive_return_gate():
    m=metrics([trade("a",-20_000,1),trade("b",50_000,2)])
    assert m["arithmetic_return_sum"] < -1 or metrics([trade("x",-20_000,1)])["arithmetic_return_sum"] < -1
    assert m["portfolio_return_decimal"] == -1
    checks,_=gates(m)
    assert checks["return_positive"] is False


def test_scope_invariant_has_no_dev_or_validation_ids_in_test():
    payload=json.loads((RESULTS/"currency_strength_audit_scope.json").read_text())
    scopes=payload["scopes"]
    assert not ((set(scopes["dev"]["trade_ids"]) | set(scopes["validation"]["trade_ids"])) &
                set(scopes["chronological_test"]["trade_ids"]))
    assert payload["leakage_invariant"]["no_dev_or_validation_trade_id_in_chronological_test"]


def test_selected_config_is_identical_when_test_outcomes_hidden():
    payload=json.loads((RESULTS/"currency_strength_audit_leakage.json").read_text())
    assert all("TEST" not in row for row in payload["candidate_selection_inputs"])
    selected=rank_selection_inputs(payload["candidate_selection_inputs"])
    assert frozen_config_hash(selected["configuration"]) == payload["selected_configuration_hash"]
    assert payload["hidden_test_reproducibility"]["identical"]


def test_currency_boundary_is_inclusive_at_exactly_half():
    assert currency_boundary_passes({"USD":.5,"EUR":.5})
    assert not currency_boundary_passes({"USD":.5000001,"EUR":.4999999})
    assert not currency_boundary_passes({"USD":.4,"EUR":.6})


def test_frozen_config_metrics_reproducible_without_grid(monkeypatch):
    import run_currency_strength_research as runner
    monkeypatch.setattr(runner,"build_grid",lambda: pytest.fail("grid iteration forbidden in audit"))
    regenerated=run_audit()
    artifact=json.loads((RESULTS/"currency_strength_frozen_candidate_corrected.json").read_text())
    assert regenerated["selected_configuration"] == FROZEN_CONFIG
    assert regenerated["selected_configuration_hash"] == frozen_config_hash()
    assert regenerated["chronological_test"]["profit_factor"] == artifact["chronological_test"]["profit_factor"]
    assert artifact["gate_bearing_scope"] == "chronological_test"
