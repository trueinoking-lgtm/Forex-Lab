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


def test_open_risk_released_on_close_restores_capacity():
    state = PortfolioRiskState({"initial_equity": 10000, "max_portfolio_risk_pct": 4})
    state.register_open("trend", 300)
    assert not state.halt_new_entries()  # 300 < 400 cap
    state.register_open("trend", 150)
    assert state.halt_new_entries()  # 450 >= 400 cap
    state.register_close(10.0, strategy="trend", risk_amt=150)
    assert not state.halt_new_entries()  # back to 300 < 400


def test_register_close_missing_args_does_not_release_risk():
    state = PortfolioRiskState({"initial_equity": 10000, "max_portfolio_risk_pct": 4})
    state.register_open("trend", 450)
    assert state.halt_new_entries()
    state.register_close(5.0)  # legacy call: no release args
    assert state.halt_new_entries()


def test_non_finite_threshold_or_state_fails_closed():
    with pytest.raises(ValueError):
        PortfolioRiskState({"initial_equity": 10000, "max_drawdown_pct": float("nan")})
    state = PortfolioRiskState({"initial_equity": 10000})
    state.register_open("trend", float("nan"))
    reasons = state.halt_reasons()
    assert reasons and "corrupt" in reasons[0]
    assert state.halt_new_entries()
    state2 = PortfolioRiskState({"initial_equity": 10000})
    state2.register_close(float("inf"))
    assert state2.halt_new_entries()


def test_negative_threshold_rejected():
    with pytest.raises(ValueError):
        PortfolioRiskState({"initial_equity": 10000, "max_drawdown_pct": -1.0})


def test_build_portfolio_risk_halts_on_open_risk(tmp_path):
    # End-to-end: an open demo order whose reserved risk exceeds the portfolio
    # cap must make build_portfolio_risk() produce a halting state. We use a
    # tiny max_portfolio_risk_pct so a single order's ~$75 risk trips it.
    import sqlite3, yaml
    dbp = tmp_path / "t.db"
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE DemoExecutionOrder (id INTEGER PRIMARY KEY, strategy TEXT, "
               "symbol TEXT, entry REAL, stop_loss REAL, units REAL, status TEXT)")
    db.execute("INSERT INTO DemoExecutionOrder (strategy, symbol, entry, stop_loss, units, status) "
               "VALUES ('trend','EURUSD',1.1000,1.0900,100,'filled')")
    db.commit()
    from run_execution import build_portfolio_risk
    base = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())
    base["risk"] = {"max_portfolio_risk_pct": 0.1}  # cap = $10, one order reserves ~$75
    state = build_portfolio_risk(db, base)
    assert state.halt_new_entries(), state.halt_reasons()

