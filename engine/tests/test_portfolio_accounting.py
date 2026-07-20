"""Regression tests for canonical cross-pair portfolio accounting."""
from __future__ import annotations

import pandas as pd
import pytest

try:
    from engine.run_session_breakout_research import aggregate
    from engine.src.paper_sim import simulate
    from engine.src.trade_ledger import SHARED_NOTIONAL, extract_trades, lifecycle_metrics
except ImportError:
    from run_session_breakout_research import aggregate
    from src.paper_sim import simulate
    from src.trade_ledger import SHARED_NOTIONAL, extract_trades, lifecycle_metrics


def _series(values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values),
                                                freq="h", tz="UTC"))


def _closed(symbol, prices, direction=1, costs=0):
    signal = [direction, direction, 0, 0]
    return extract_trades(_series(prices), _series(signal), strategy="test",
                          symbol=symbol, spread_bps=costs)[0]


@pytest.mark.parametrize("symbol,prices,direction,expected", [
    ("EURUSD", [1.0, 1.0, 1.01, 1.01], 1, 1_000.0),
    ("EURUSD", [1.0, 1.0, .99, .99], -1, 1_000.0),
    ("USDJPY", [150.0, 150.0, 151.5, 151.5], 1, 1_000.0),
    ("USDJPY", [150.0, 150.0, 148.5, 148.5], -1, 1_000.0),
])
def test_pair_price_moves_are_normalized(symbol, prices, direction, expected):
    trade = _closed(symbol, prices, direction)
    assert trade["gross_pnl"] == pytest.approx(expected)
    assert trade["net_pnl"] == pytest.approx(expected)
    assert trade["return_pct"] == pytest.approx(expected / SHARED_NOTIONAL)


def test_same_percentage_move_has_same_pnl_across_price_levels():
    eur = _closed("EURUSD", [1, 1, 1.01, 1.01])
    jpy = _closed("USDJPY", [150, 150, 151.5, 151.5])
    assert eur["gross_pnl"] == pytest.approx(jpy["gross_pnl"])


def test_bps_cost_is_account_currency_and_price_independent():
    eur = _closed("EURUSD", [1, 1, 1, 1], costs=3)
    jpy = _closed("USDJPY", [150, 150, 150, 150], costs=3)
    assert eur["total_cost"] == jpy["total_cost"] == 30


def test_return_and_expectancy_derive_from_same_net_pnl():
    trades = [_closed("EURUSD", [1, 1, 1.01, 1.01]),
              _closed("USDJPY", [150, 150, 148.5, 148.5])]
    metric = aggregate(trades)
    expected_net = sum(t["net_pnl"] for t in trades)
    assert metric["net_pnl"] == pytest.approx(expected_net)
    assert metric["return"] == pytest.approx(expected_net / metric["initial_equity"])
    assert metric["expectancy"] == pytest.approx(expected_net / len(trades))


def test_aggregate_pf_is_combined_profit_over_combined_loss_not_mean():
    trades = [_closed("EURUSD", [1, 1, 1.02, 1.02]),
              _closed("USDJPY", [150, 150, 148.5, 148.5])]
    metric = aggregate(trades)
    assert metric["profit_factor"] == pytest.approx(
        metric["gross_profit"] / metric["gross_loss"])
    assert metric["profit_factor"] == pytest.approx(2.0)


def test_open_trades_are_excluded_from_all_closed_trade_metrics():
    closed = _closed("EURUSD", [1, 1, 1.01, 1.01])
    opened = extract_trades(_series([1, 1, 1.02, 1.03]), _series([1, 1, 1, 1]),
                            strategy="test", symbol="EURUSD")[0]
    metric = aggregate([closed, opened])
    assert metric["trade_count"] == 1
    assert metric["net_pnl"] == closed["net_pnl"]
    assert lifecycle_metrics([closed, opened])["open_trade_count"] == 1


def _bankruptcy_sim(exit_price, signals=1):
    idx = pd.date_range("2026-01-01", periods=5, freq="D", tz="UTC")
    price = pd.Series([100, exit_price, 100, 105, 110], index=idx)
    items = [{"timestamp": str(idx[0]), "side": "buy", "stop_loss": 99,
              "take_profit": 104, "tradeable": True}]
    if signals > 1:
        items.append({"timestamp": str(idx[2]), "side": "buy", "stop_loss": 99,
                      "take_profit": 104, "tradeable": True})
    return simulate(items, price, cost_bps=0, initial_capital=100,
                    risk_pct=100)


def test_exact_equity_loss_marks_bankrupt():
    result = _bankruptcy_sim(0)
    assert result["equity_curve"][-1] == 0
    assert result["bankrupt"] is True


def test_excessive_gap_loss_is_capped_at_available_equity():
    result = _bankruptcy_sim(-10)
    assert result["trades"][0]["uncapped_pnl"] < -100
    assert result["trades"][0]["pnl"] == -100
    assert result["trades"][0]["loss_capped_at_equity"] is True


def test_no_entries_are_accepted_after_bankruptcy():
    result = _bankruptcy_sim(-10, signals=2)
    assert len(result["trades"]) == 1
    assert result["metrics"]["bankrupt"] is True


def test_zero_initial_equity_is_bankrupt_and_never_trades():
    idx = pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC")
    signal = {"timestamp": str(idx[0]), "side": "buy", "stop_loss": 99,
              "take_profit": 101, "tradeable": True}
    result = simulate([signal], pd.Series([100, 101], index=idx), 0,
                      initial_capital=0)
    assert result["bankrupt"] and not result["trades"]
