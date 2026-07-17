"""Tests for portfolio-level risk budgets and circuit breakers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.execution.risk_budget import PortfolioRiskState, load_risk_cfg


def test_drawdown_from_rising_peak_halts():
    state = PortfolioRiskState({"initial_equity": 10000, "max_drawdown_pct": 6})
    state.update_equity(12000)
    state.update_equity(10800)
    assert state.max_drawdown_pct() == pytest.approx(10.0)
    assert state.halt_new_entries()


def test_daily_loss_limit_halts():
    state = PortfolioRiskState({"initial_equity": 10000, "daily_loss_limit_pct": 3})
    state.register_close(-301)
    assert state.halt_new_entries()


def test_open_portfolio_risk_limit_halts():
    state = PortfolioRiskState({"initial_equity": 10000, "max_portfolio_risk_pct": 4})
    state.register_open("trend", 401)
    assert state.halt_new_entries()


def test_healthy_state_allows_entries():
    state = PortfolioRiskState({"initial_equity": 10000})
    state.update_equity(10100)
    state.register_close(-100)
    state.register_open("trend", 100)
    assert not state.halt_new_entries()


@pytest.mark.parametrize("curve", [[], [None]])
def test_missing_equity_fails_closed(curve):
    state = PortfolioRiskState({})
    state.equity_curve = curve
    assert state.halt_new_entries()


def test_per_strategy_cap_includes_existing_and_proposed_risk():
    state = PortfolioRiskState({"initial_equity": 10000, "per_strategy_risk_pct": 1})
    state.register_open("trend", 60)
    assert state.per_strategy_ok("trend", 40)
    assert not state.per_strategy_ok("trend", 40.01)
    assert state.per_strategy_ok("range", 100)


def test_load_risk_cfg_supplies_defaults_and_preserves_overrides():
    cfg = load_risk_cfg({"risk": {"max_drawdown_pct": 5.0}})
    assert cfg == {
        "max_drawdown_pct": 5.0,
        "daily_loss_limit_pct": 3.0,
        "max_portfolio_risk_pct": 4.0,
        "per_strategy_risk_pct": 1.0,
    }
