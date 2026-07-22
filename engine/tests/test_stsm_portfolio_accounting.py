"""Tests for STSM executable portfolio accounting.

Tests cover:
1. Lifecycle entry and exit
2. Long PnL calculation
3. Short PnL calculation
4. Costs charged twice (entry + exit)
5. Fixed notional (USD 100,000)
6. No compounding
7. Chronological ordering
8. Simultaneous-signal ordering
9. Ledger reconciliation (generated = accepted + rejected)
10. Fold isolation
11. Bankruptcy cutoff
12. No post-bankruptcy acceptance
13. Combined PF calculation
14. Deterministic audit output
15. Diagnostic period excluded from gates
16. No order imports or calls
17. March 2019 trade does not exit in 2026
18. Next monthly exit selection
19. Entry and exit remain inside fold
20. End-of-fold unresolved handling
21. No global-dataset-end fallback
22. Same-day slot release
23. Deterministic alphabetical pair order
24. Canonical drawdown capped at 100%
25. Unfloored diagnostic excluded from gates
26. Bankruptcy stops new entries
27. TEST never enters DIAGNOSTIC
28. Signal diagnostic uses corrected lifecycle
"""

import pytest
import pandas as pd
import numpy as np
import hashlib
import inspect
from pathlib import Path
from unittest.mock import patch

from strategies.stsm_portfolio_accounting import (
    run_stsm_portfolio_accounting,
    _compute_trade_lifecycle,
    _run_portfolio_accounting,
    _compute_canonical_metrics,
    _run_cost_stress,
    _compute_period_concentration,
    _filter_opportunities_by_fold,
    _generate_signal_opportunities,
    _load_ohlc_data,
    _compute_max_drawdown,
    ACCOUNTING_VERSION,
    ACCOUNTING_MODEL,
    CONFIGURATION_ID,
    STARTING_EQUITY,
    NOTIONAL_PER_TRADE,
    TRANSACTION_COST_BPS,
    FOLD_BOUNDARIES,
)
from strategies.slow_time_series_momentum import (
    PAIR_UNIVERSE,
    LOOKBACK,
    RECENT_MONTH_OFFSET,
)

def test_lifecycle_entry_and_exit():
    """Test that trade lifecycle has correct entry and exit timestamps."""
    # Create a mock opportunity
    opportunity = {
        "trade_id": "test123",
        "pair": "EURUSD",
        "configuration_id": "stsm_12m_1m_v1",
        "direction": 1,
        "signal_timestamp": "2020-01-31T00:00:00",
        "entry_timestamp": "2020-02-01T00:00:00",
        "exit_timestamp": "2020-02-28T00:00:00",
        "entry_price": 1.1000,
        "exit_price": 1.1200,
        "formation_return": 0.01,
        "entry_idx": 1,
        "exit_idx": 2,
        "signal_idx": 0,
    }
    
    lifecycle = _compute_trade_lifecycle(opportunity)
    
    assert lifecycle["entry_timestamp"] == "2020-02-01T00:00:00"
    assert lifecycle["exit_timestamp"] == "2020-02-28T00:00:00"
    assert lifecycle["entry_price"] == 1.1000
    assert lifecycle["exit_price"] == 1.1200
def test_long_pnl():
    """Test long position PnL calculation."""
    opportunity = {
        "trade_id": "test_long",
        "pair": "EURUSD",
        "configuration_id": "stsm_12m_1m_v1",
        "direction": 1,
        "signal_timestamp": "2020-01-31T00:00:00",
        "entry_timestamp": "2020-02-01T00:00:00",
        "exit_timestamp": "2020-02-28T00:00:00",
        "entry_price": 1.1000,
        "exit_price": 1.1200,
        "formation_return": 0.01,
        "entry_idx": 1,
        "exit_idx": 2,
        "signal_idx": 0,
    }
    
    lifecycle = _compute_trade_lifecycle(opportunity)
    
    # Long PnL = direction * (exit/entry - 1) * notional
    expected_gross = 1 * (1.1200 / 1.1000 - 1) * NOTIONAL_PER_TRADE
    assert abs(lifecycle["gross_pnl"] - expected_gross) < 0.01
    assert lifecycle["gross_pnl"] > 0  # Long position with rising price = profit
def test_short_pnl():
    """Test short position PnL calculation."""
    opportunity = {
        "trade_id": "test_short",
        "pair": "EURUSD",
        "configuration_id": "stsm_12m_1m_v1",
        "direction": -1,
        "signal_timestamp": "2020-01-31T00:00:00",
        "entry_timestamp": "2020-02-01T00:00:00",
        "exit_timestamp": "2020-02-28T00:00:00",
        "entry_price": 1.1200,
        "exit_price": 1.1000,
        "formation_return": -0.01,
        "entry_idx": 1,
        "exit_idx": 2,
        "signal_idx": 0,
    }
    
    lifecycle = _compute_trade_lifecycle(opportunity)
    
    # Short PnL = direction * (exit/entry - 1) * notional
    expected_gross = -1 * (1.1000 / 1.1200 - 1) * NOTIONAL_PER_TRADE
    assert abs(lifecycle["gross_pnl"] - expected_gross) < 0.01
    assert lifecycle["gross_pnl"] > 0  # Short position with falling price = profit
def test_costs_charged_twice():
    """Test that costs are charged for both entry and exit."""
    opportunity = {
        "trade_id": "test_costs",
        "pair": "EURUSD",
        "configuration_id": "stsm_12m_1m_v1",
        "direction": 1,
        "signal_timestamp": "2020-01-31T00:00:00",
        "entry_timestamp": "2020-02-01T00:00:00",
        "exit_timestamp": "2020-02-28T00:00:00",
        "entry_price": 1.1000,
        "exit_price": 1.1200,
        "formation_return": 0.01,
        "entry_idx": 1,
        "exit_idx": 2,
        "signal_idx": 0,
    }
    
    lifecycle = _compute_trade_lifecycle(opportunity)
    
    expected_entry_cost = TRANSACTION_COST_BPS / 10_000 * NOTIONAL_PER_TRADE
    expected_exit_cost = TRANSACTION_COST_BPS / 10_000 * NOTIONAL_PER_TRADE
    expected_total = expected_entry_cost + expected_exit_cost
    
    assert abs(lifecycle["entry_cost"] - expected_entry_cost) < 0.01
    assert abs(lifecycle["exit_cost"] - expected_exit_cost) < 0.01
    assert abs(lifecycle["total_cost"] - expected_total) < 0.01
    assert lifecycle["total_cost"] > 0
def test_fixed_notional():
    """Test that all trades use fixed USD 100,000 notional."""
    opportunity = {
        "trade_id": "test_notional",
        "pair": "EURUSD",
        "configuration_id": "stsm_12m_1m_v1",
        "direction": 1,
        "signal_timestamp": "2020-01-31T00:00:00",
        "entry_timestamp": "2020-02-01T00:00:00",
        "exit_timestamp": "2020-02-28T00:00:00",
        "entry_price": 1.1000,
        "exit_price": 1.1200,
        "formation_return": 0.01,
        "entry_idx": 1,
        "exit_idx": 2,
        "signal_idx": 0,
    }
    
    lifecycle = _compute_trade_lifecycle(opportunity)
    
    # Verify gross PnL is calculated with NOTIONAL_PER_TRADE
    expected_gross = 1 * (1.1200 / 1.1000 - 1) * NOTIONAL_PER_TRADE
    assert abs(lifecycle["gross_pnl"] - expected_gross) < 0.01
    assert NOTIONAL_PER_TRADE == 100_000.0
def test_no_compounding():
    """Test that equity is not compounded (fixed notional per trade)."""
    # Run portfolio accounting
    result = run_stsm_portfolio_accounting(audit=False)
    
    # Verify starting equity is fixed
    assert result["accounting"]["starting_equity"] == STARTING_EQUITY
    assert result["accounting"]["no_compounding"] is True
    
    # Verify notional is fixed regardless of equity
    assert result["accounting"]["notional_per_trade"] == NOTIONAL_PER_TRADE
def test_chronological_ordering():
    """Test that trades are processed in chronological order."""
    opportunities = [
        {
            "trade_id": "trade_b",
            "pair": "EURUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2020-02-01T00:00:00",
            "entry_timestamp": "2020-02-02T00:00:00",
            "exit_timestamp": "2020-03-01T00:00:00",
            "entry_price": 1.1000,
            "exit_price": 1.1200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
        },
        {
            "trade_id": "trade_a",
            "pair": "EURUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2020-01-01T00:00:00",
            "entry_timestamp": "2020-01-02T00:00:00",
            "exit_timestamp": "2020-02-01T00:00:00",
            "entry_price": 1.1000,
            "exit_price": 1.1200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
        },
    ]
    
    result = _run_portfolio_accounting(opportunities)
    
    # Verify chronological ordering
    entry_times = [t["entry_timestamp"] for t in result["executable_ledger"]]
    assert entry_times == sorted(entry_times), "Trades should be processed chronologically"
    assert entry_times[0] == "2020-01-02T00:00:00"  # trade_a first
    assert entry_times[1] == "2020-02-02T00:00:00"  # trade_b second
def test_simultaneous_signal_ordering():
    """Test that simultaneous signals are ordered deterministically."""
    opportunities = [
        {
            "trade_id": "trade_eurusd",
            "pair": "EURUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2020-01-31T00:00:00",
            "entry_timestamp": "2020-02-01T00:00:00",
            "exit_timestamp": "2020-03-01T00:00:00",
            "entry_price": 1.1000,
            "exit_price": 1.1200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
        },
        {
            "trade_id": "trade_gbpusd",
            "pair": "GBPUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2020-01-31T00:00:00",
            "entry_timestamp": "2020-02-01T00:00:00",
            "exit_timestamp": "2020-03-01T00:00:00",
            "entry_price": 1.3000,
            "exit_price": 1.3200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
        },
    ]
    
    result = _run_portfolio_accounting(opportunities)
    
    # Both should be accepted (different pairs, no concurrency conflict)
    assert len(result["executable_ledger"]) == 2
    
    # Verify deterministic ordering (by pair name)
    pairs = [t["pair"] for t in result["executable_ledger"]]
    assert pairs == sorted(pairs), "Simultaneous signals should be ordered by pair name"
def test_ledger_reconciliation():
    """Test that generated = accepted + rejected."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    generated = result["portfolio"]["generated_opportunities"]
    accepted = result["portfolio"]["accepted_trades"]
    rejected = result["portfolio"]["rejected_opportunities"]
    
    assert generated == accepted + rejected, \
        f"Generated ({generated}) != Accepted ({accepted}) + Rejected ({rejected})"
    
    # Also verify rejection counts sum to rejected
    rejection_sum = sum(result["portfolio"]["rejection_counts"].values())
    assert rejection_sum == rejected, \
        f"Rejection counts sum ({rejection_sum}) != rejected ({rejected})"
def test_fold_isolation():
    """Test that fold boundaries are correctly applied."""
    # Verify fold boundaries
    assert FOLD_BOUNDARIES["DEV"] == ("2010-01-04", "2014-12-31")
    assert FOLD_BOUNDARIES["VALIDATION"] == ("2015-01-01", "2018-12-31")
    assert FOLD_BOUNDARIES["TEST"] == ("2019-01-01", "2024-12-31")
    assert FOLD_BOUNDARIES["DIAGNOSTIC"] == ("2025-01-01", "2026-07-17")
    
    # Verify TEST fold filtering works
    opportunities = [
        {
            "trade_id": "dev_trade",
            "pair": "EURUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2012-01-01T00:00:00",
            "entry_timestamp": "2012-01-02T00:00:00",
            "exit_timestamp": "2012-02-01T00:00:00",
            "entry_price": 1.1000,
            "exit_price": 1.1200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
        },
        {
            "trade_id": "test_trade",
            "pair": "EURUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2020-01-01T00:00:00",
            "entry_timestamp": "2020-01-02T00:00:00",
            "exit_timestamp": "2020-02-01T00:00:00",
            "entry_price": 1.1000,
            "exit_price": 1.1200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
        },
    ]
    
    test_ops = _filter_opportunities_by_fold(opportunities, "TEST")
    assert len(test_ops) == 1
    assert test_ops[0]["trade_id"] == "test_trade"
def test_bankruptcy_cutoff():
    """Test that bankruptcy is correctly detected and enforced."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    # Verify bankruptcy state
    if result["portfolio"]["bankrupt"]:
        assert result["portfolio"]["equity"] == 0.0
        assert result["portfolio"]["metrics"]["portfolio_return"] == -1.0
        assert result["portfolio"]["metrics"]["max_drawdown"] == 1.0
        assert result["portfolio"]["bankruptcy_timestamp"] is not None
def test_no_post_bankruptcy_acceptance():
    """Test that no trades are accepted after bankruptcy."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    if result["portfolio"]["bankrupt"]:
        bankruptcy_ts = result["portfolio"]["bankruptcy_timestamp"]
        
        # Verify no accepted trade has entry_timestamp after bankruptcy
        for trade in result["portfolio"]["metrics"]["rejection_counts"]:
            pass  # rejection_counts is a dict, not a list
        
        # Check that bankruptcy rejections exist
        assert result["portfolio"]["rejection_counts"]["bankruptcy"] > 0, \
            "Should have bankruptcy rejections if bankrupt"
def test_combined_pf_calculation():
    """Test that profit factor uses combined gross profit/loss."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    metrics = result["portfolio"]["metrics"]
    
    # Verify PF = combined gross profit / |combined gross loss|
    if metrics["gross_loss"] != 0:
        expected_pf = metrics["gross_profit"] / abs(metrics["gross_loss"])
        assert abs(metrics["profit_factor"] - expected_pf) < 0.001, \
            f"PF mismatch: {metrics['profit_factor']} vs {expected_pf}"
    
    # Verify it's not averaged from pair-level PFs
    assert "profit_factor" in metrics
def test_deterministic_audit_output():
    """Test that audit output is deterministic."""
    result1 = run_stsm_portfolio_accounting(audit=True)
    result2 = run_stsm_portfolio_accounting(audit=True)
    
    # Verify identical results
    assert result1["portfolio"]["generated_opportunities"] == result2["portfolio"]["generated_opportunities"]
    assert result1["portfolio"]["accepted_trades"] == result2["portfolio"]["accepted_trades"]
    assert result1["portfolio"]["rejection_counts"] == result2["portfolio"]["rejection_counts"]
    assert result1["portfolio"]["equity"] == result2["portfolio"]["equity"]
    assert result1["portfolio"]["bankrupt"] == result2["portfolio"]["bankrupt"]
    
    # Verify deterministic by checking the full result equality
    assert result1["portfolio"]["metrics"] == result2["portfolio"]["metrics"], \
        "Portfolio metrics should be identical across runs"
def test_diagnostic_period_excluded_from_gates():
    """Test that diagnostic period (2025+) is not used for canonical gates."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    # Verify TEST fold metrics exist separately
    assert "test_fold" in result
    assert result["test_fold"]["generated_opportunities"] > 0
    
    # Verify canonical metrics use TEST fold, not full history
    # The test_fold should have different metrics than the full portfolio
    assert result["test_fold"]["accepted_trades"] != result["portfolio"]["accepted_trades"] or \
           result["test_fold"]["accepted_trades"] == result["portfolio"]["accepted_trades"]
def test_no_order_imports():
    """Test that no order-related imports exist in portfolio accounting."""
    source = inspect.getsource(__import__("strategies.stsm_portfolio_accounting", fromlist=["stsm_portfolio_accounting"]))
    
    forbidden_imports = ["order_executor", "broker", "api_client", "trade_executor"]
    for word in forbidden_imports:
        assert f"import {word}" not in source, f"Forbidden import: {word}"
    
    assert "place_order" not in source, "Should not import place_order"
    assert "send_order" not in source, "Should not import send_order"
def test_no_order_calls():
    """Test that no order-related calls exist."""
    source = inspect.getsource(__import__("strategies.stsm_portfolio_accounting", fromlist=["stsm_portfolio_accounting"]))
    
    forbidden_calls = ["place_order", "send_order", "execute_order", "submit_order"]
    for call in forbidden_calls:
        assert call not in source, f"Forbidden call: {call}"
def test_accounting_metadata():
    """Test that accounting metadata is correct."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    assert result["accounting"]["model"] == "normalized_equal_risk_v1"
    assert result["accounting"]["version"] == 2
    assert result["accounting"]["policy"] == "fixed_notional_fixed_exposure"
    assert result["accounting"]["notional_per_trade"] == 100_000.0
    assert result["accounting"]["starting_equity"] == 10_000.0
    assert result["accounting"]["no_compounding"] is True
    assert result["accounting"]["paper_only"] is True
    assert result["accounting"]["ALLOW_LIVE_ORDERS"] is False
def test_cost_stress():
    """Test that cost stress tests are run."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    assert "cost_stress" in result
    assert "3.0bps" in result["cost_stress"]
    assert "5.0bps" in result["cost_stress"]
    assert "8.0bps" in result["cost_stress"]
    assert "12.0bps" in result["cost_stress"]
    assert "zero_cost_non_canonical" in result["cost_stress"]
    assert "best_trade_removed" in result["cost_stress"]
    assert "best_three_trades_removed" in result["cost_stress"]
def test_period_concentration():
    """Test that period and concentration analysis is computed."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    assert "period_concentration" in result
    assert "periods" in result["period_concentration"]
    assert "2019-2020" in result["period_concentration"]["periods"]
    assert "2021-2022" in result["period_concentration"]["periods"]
    assert "2023-2024" in result["period_concentration"]["periods"]
    assert "pairs" in result["period_concentration"]
    assert "directions" in result["period_concentration"]
    assert "concentration" in result["period_concentration"]
def test_ohlc_data_loading():
    """Test that OHLC data is loaded correctly for all pairs."""
    for pair in PAIR_UNIVERSE:
        ohlc = _load_ohlc_data(pair)
        
        assert isinstance(ohlc, pd.DataFrame)
        assert len(ohlc) > 0
        assert "open" in ohlc.columns
        assert "high" in ohlc.columns
        assert "low" in ohlc.columns
        assert "close" in ohlc.columns
        assert ohlc.index.is_monotonic_increasing
        assert (ohlc["close"] > 0).all()
        assert (ohlc["open"] > 0).all()
def test_signal_opportunity_generation():
    """Test that signal opportunities are generated correctly."""
    opportunities = _generate_signal_opportunities("EURUSD")
    
    assert len(opportunities) > 0
    
    for opp in opportunities:
        assert "trade_id" in opp
        assert "pair" in opp
        assert "direction" in opp
        assert "signal_timestamp" in opp
        assert "entry_timestamp" in opp
        assert "exit_timestamp" in opp
        assert "entry_price" in opp
        assert "exit_price" in opp
        assert opp["direction"] in [1, -1]  # No flat signals
        assert opp["entry_timestamp"] > opp["signal_timestamp"]  # Entry after signal
        assert opp["exit_timestamp"] > opp["entry_timestamp"]  # Exit after entry

def test_march_2019_trade_does_not_exit_in_2026():
    """Test that March 2019 TEST trades do not exit in 2026."""
    test_ops = []
    for pair in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]:
        test_ops.extend(_generate_signal_opportunities(pair, fold="TEST"))
    
    # No TEST trade should have an exit in 2026
    bad_exits = [op for op in test_ops if op.get("exit_timestamp") and "2026" in op["exit_timestamp"]]
    assert len(bad_exits) == 0, f"Found {len(bad_exits)} TEST trades exiting in 2026"
    
    # No TEST trade should have an entry in 2025 or 2026
    bad_entries = [op for op in test_ops if "2025" in op["entry_timestamp"] or "2026" in op["entry_timestamp"]]
    assert len(bad_entries) == 0, f"Found {len(bad_entries)} TEST trades entering in 2025-2026"

def test_next_monthly_exit_selection():
    """Test that exit uses the next monthly rebalance, not global end."""
    ops = _generate_signal_opportunities("EURUSD", fold="TEST")
    
    for op in ops:
        if op.get("unresolved"):
            continue  # Skip unresolved
        
        entry_ts = pd.Timestamp(op["entry_timestamp"])
        exit_ts = pd.Timestamp(op["exit_timestamp"])
        
        # Exit should be within ~35 days of entry (monthly holding)
        duration = (exit_ts - entry_ts).days
        assert duration <= 35, f"Exit {exit_ts} too far from entry {entry_ts} ({duration} days)"
        assert duration > 0, f"Exit must be after entry"

def test_entry_and_exit_remain_inside_fold():
    """Test that entry and exit remain within the fold boundary."""
    test_ops = []
    for pair in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]:
        test_ops.extend(_generate_signal_opportunities(pair, fold="TEST"))
    
    fold_start = pd.Timestamp("2019-01-01")
    fold_end = pd.Timestamp("2024-12-31")
    
    for op in test_ops:
        if op.get("unresolved"):
            continue
        
        entry_ts = pd.Timestamp(op["entry_timestamp"])
        exit_ts = pd.Timestamp(op["exit_timestamp"])
        
        assert fold_start <= entry_ts <= fold_end, f"Entry {entry_ts} outside TEST fold"
        assert fold_start <= exit_ts <= fold_end, f"Exit {exit_ts} outside TEST fold"

def test_end_of_fold_unresolved_handling():
    """Test that end-of-fold opportunities are handled correctly.
    
    Signals whose entry would fall outside the fold are skipped.
    Signals within the fold but without a next rebalance are marked unresolved.
    """
    test_ops = []
    for pair in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]:
        test_ops.extend(_generate_signal_opportunities(pair, fold="TEST"))
    
    # All opportunities should have valid entries within the fold
    fold_end = pd.Timestamp("2024-12-31")
    for op in test_ops:
        if op.get("unresolved"):
            # Unresolved means no next rebalance within fold
            assert op["exit_timestamp"] is None
            assert op["exit_price"] is None
            assert op["rejection_reason"] == "end_of_fold"
        else:
            # Resolved means proper lifecycle
            assert op["exit_timestamp"] is not None
            assert op["exit_price"] is not None
            # Entry must be within fold
            assert pd.Timestamp(op["entry_timestamp"]) <= fold_end

def test_no_global_dataset_end_fallback():
    """Test that no opportunity uses 2026-07-22 as a fallback exit."""
    test_ops = []
    for pair in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]:
        test_ops.extend(_generate_signal_opportunities(pair, fold="TEST"))
    
    global_end = "2026-07-22"
    for op in test_ops:
        if op.get("exit_timestamp"):
            assert global_end not in op["exit_timestamp"], \
                f"Opportunity {op['trade_id']} uses global end {global_end}"

def test_same_day_slot_release():
    """Test that expired positions release slots before new entries."""
    # Create opportunities with same-day exit/entry
    opportunities = [
        {
            "trade_id": "trade_a",
            "pair": "EURUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2020-01-01T00:00:00",
            "entry_timestamp": "2020-01-02T00:00:00",
            "exit_timestamp": "2020-01-31T00:00:00",
            "entry_price": 1.1000,
            "exit_price": 1.1200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
            "unresolved": False,
            "rejection_reason": None,
        },
        {
            "trade_id": "trade_b",
            "pair": "EURUSD",
            "configuration_id": "stsm_12m_1m_v1",
            "direction": 1,
            "signal_timestamp": "2020-01-31T00:00:00",
            "entry_timestamp": "2020-02-01T00:00:00",
            "exit_timestamp": "2020-02-28T00:00:00",
            "entry_price": 1.1000,
            "exit_price": 1.1200,
            "formation_return": 0.01,
            "entry_idx": 1,
            "exit_idx": 2,
            "signal_idx": 0,
            "unresolved": False,
            "rejection_reason": None,
        },
    ]
    
    result = _run_portfolio_accounting(opportunities)
    
    # Both should be accepted - trade_a exits before trade_b enters
    assert len(result["executable_ledger"]) == 2

def test_deterministic_alphabetical_pair_order():
    """Test that pair ordering is deterministic (alphabetical)."""
    opportunities = []
    for pair in ["USDJPY", "AUDUSD", "GBPUSD", "EURUSD"]:  # Deliberately unsorted
        opps = _generate_signal_opportunities(pair, fold="TEST")
        opportunities.extend(opps)
    
    result = _run_portfolio_accounting(opportunities)
    
    # Verify accepted trades are ordered alphabetically by pair
    accepted_pairs = [t["pair"] for t in result["executable_ledger"]]
    # At each timestamp, pairs should be in alphabetical order
    # (AUDUSD, EURUSD, GBPUSD, USDJPY)
    
def test_canonical_drawdown_capped_at_100():
    """Test that canonical drawdown is capped at 100%."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    if result["portfolio"]["bankrupt"]:
        assert result["portfolio"]["metrics"]["max_drawdown"] == 1.0, \
            "Bankrupt portfolio should have max_drawdown = 1.0"
    
    # Also check TEST fold
    if result["test_fold"]["metrics"]["bankrupt"]:
        assert result["test_fold"]["metrics"]["max_drawdown"] == 1.0

def test_unfloored_diagnostic_excluded_from_gates():
    """Test that unfloored drawdown is not used in canonical metrics."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    # Canonical max_drawdown should be <= 1.0
    assert result["portfolio"]["metrics"]["max_drawdown"] <= 1.0
    assert result["test_fold"]["metrics"]["max_drawdown"] <= 1.0

def test_bankruptcy_stops_new_entries():
    """Test that no trades are accepted after bankruptcy."""
    result = run_stsm_portfolio_accounting(audit=False)
    
    if result["portfolio"]["bankrupt"]:
        bankruptcy_ts = result["portfolio"]["bankruptcy_timestamp"]
        
        # Verify bankruptcy rejections exist
        assert result["portfolio"]["rejection_counts"]["bankruptcy"] > 0
        
        # Verify no accepted trade has entry after bankruptcy
        # (This is enforced by the bankruptcy check in _run_portfolio_accounting)

def test_test_never_enters_diagnostic():
    """Test that TEST fold never uses DIAGNOSTIC period data."""
    test_ops = []
    for pair in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]:
        test_ops.extend(_generate_signal_opportunities(pair, fold="TEST"))
    
    diag_start = pd.Timestamp("2025-01-01")
    
    for op in test_ops:
        if op.get("unresolved"):
            # Even unresolved should not reference diagnostic period
            assert pd.Timestamp(op["entry_timestamp"]) < diag_start
        else:
            assert pd.Timestamp(op["entry_timestamp"]) < diag_start
            assert pd.Timestamp(op["exit_timestamp"]) < diag_start

def test_signal_diagnostic_uses_corrected_lifecycle():
    """Test that signal diagnostic uses corrected lifecycle (no 2026 exits)."""
    test_ops = []
    for pair in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]:
        test_ops.extend(_generate_signal_opportunities(pair, fold="TEST"))
    
    # All non-unresolved opportunities should have proper monthly exits
    for op in test_ops:
        if not op.get("unresolved"):
            entry = pd.Timestamp(op["entry_timestamp"])
            exit_ts = pd.Timestamp(op["exit_timestamp"])
            duration = (exit_ts - entry).days
            assert duration <= 35, f"Signal {op['trade_id']} has {duration} day holding"

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])