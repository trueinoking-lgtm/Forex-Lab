import json
from pathlib import Path

import pandas as pd
import pytest

from run_currency_strength_research import (
    FOLDS,
    FROZEN_CONFIG,
    gates,
    load_data,
    metrics,
    run_audit,
    simulate,
    split_ledgers,
)
from strategies.currency_strength import construct_signals


RESULTS = Path(__file__).parents[1] / "results"


@pytest.fixture(scope="module")
def audit():
    run_audit()
    ledger=json.loads((RESULTS/"currency_strength_audit_ledger_reconciliation.json").read_text())
    ids=json.loads((RESULTS/"currency_strength_audit_accepted_vs_rejected.json").read_text())
    scope=json.loads((RESULTS/"currency_strength_audit_scope.json").read_text())
    return ledger,ids,scope


def test_test_fold_count_reconciliation(audit):
    reconciliation=audit[0]["reconciliation"]
    assert reconciliation["generated_opportunities"] == (
        reconciliation["accepted_entries"]+reconciliation["rejected_bankruptcy"]+
        reconciliation["rejected_concurrency"]+reconciliation["rejected_risk_cap"]+
        reconciliation["other_rejected"])
    assert reconciliation["generated_equals_components"]


def test_executable_count_equals_accepted_completed(audit):
    ledger=audit[0]; reconciliation=ledger["reconciliation"]
    assert len(ledger["executable_portfolio_ledger"]) == reconciliation["completed_accepted_trades"]
    # Repository data currently reconcile to this deterministic count (the splitter is authoritative).
    assert reconciliation["completed_accepted_trades"] == 1908


def test_all_post_bankruptcy_opportunities_are_rejected(audit):
    ledger,ids,_=audit; rejected={row["trade_id"]:row for row in ledger["signal_opportunity_ledger"]
                                  if not row["accepted_for_portfolio"]}
    assert set(rejected) == set(ids["rejected_trade_ids"])
    assert rejected
    assert all(row["rejection_reason"]=="BANKRUPT" and not row["accepted_for_portfolio"]
               for row in rejected.values())


def test_canonical_metrics_use_only_executable_trade_ids(audit):
    ledger,_,scope=audit; executable=ledger["executable_portfolio_ledger"]
    recomputed=metrics(executable); canonical=scope["scopes"]["chronological_test"]
    for field in ("profit_factor","expectancy_usd_per_trade","portfolio_return_decimal"):
        assert canonical[field] == recomputed[field]
    expected_ids=[row["trade_id"] for row in executable]
    for ids in scope["canonical_metric_trade_ids"].values():
        assert ids == expected_ids


def test_signal_and_executable_profit_factors_are_distinct(audit):
    ledger=audit[0]
    assert ledger["signal_diagnostic_metrics"]["profit_factor"] != ledger["executable_portfolio_metrics"]["profit_factor"]
    assert ledger["signal_diagnostic_metrics"]["eligibility_allowed"] is False


def test_no_accepted_entry_after_bankruptcy(audit):
    ledger=audit[0]; bankruptcy=pd.Timestamp(ledger["reconciliation"]["bankruptcy_timestamp"])
    assert all(pd.Timestamp(row["entry_timestamp"]) <= bankruptcy
               for row in ledger["executable_portfolio_ledger"])


def test_minimum_trade_gate_fails_below_300(audit):
    executable=audit[0]["executable_portfolio_ledger"][:299]
    checks,_=gates(metrics(executable))
    assert checks["trades_gte_300"] is False


def test_trade_id_determinism_for_test_fold():
    frames,_=load_data(full_history=True)
    closes=pd.DataFrame({pair:frame.close for pair,frame in frames.items()})
    reference_closes=closes.loc["2022-01-03":]
    research_frames={pair:frame.reindex(reference_closes.index) for pair,frame in frames.items()}
    signals=construct_signals(reference_closes,FROZEN_CONFIG["lookback"],FROZEN_CONFIG["method"],FROZEN_CONFIG["filter"])
    test_ix=closes.loc[FOLDS["TEST"][0]:FOLDS["TEST"][1]].index
    args=(research_frames,signals,FROZEN_CONFIG["lookback"],FROZEN_CONFIG["holding"],
          FROZEN_CONFIG["atr_stop"],FROZEN_CONFIG["target_r"])
    first=split_ledgers(simulate(*args,allowed_index=test_ix))["signal_ledger"]
    second=split_ledgers(simulate(*args,allowed_index=test_ix))["signal_ledger"]
    assert [row["trade_id"] for row in first] == [row["trade_id"] for row in second]
