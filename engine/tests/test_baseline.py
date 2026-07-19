import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import baseline


def _price(n=80):
    index = pd.date_range("2025-01-01", periods=n, tz="UTC")
    return pd.Series(1.1 * np.cumprod(1 + np.sin(np.arange(n) / 5) / 100), index=index)


def _ctx():
    return {"walk_forward": {"train_days": 20, "test_days": 10, "step_days": 10},
            "cost_bps": 3, "initial_capital": 10_000,
            "periods_per_year": 252, "risk_free_rate": 0.0}


def _strategy(price, period=4):
    return np.sign(price.pct_change(period)).fillna(0.0)


def test_controls_are_causal_and_no_trade_is_flat_after_costs():
    price = _price()
    assert (baseline.no_trade(price) == 0).all()
    assert baseline.fixed_period_momentum(price).iloc[:20].equals(
        baseline.fixed_period_momentum(price.iloc[:20]))
    report = baseline.build_report(price, {"test": (_strategy, {"period": 4})}, _ctx(),
                                   symbol="EURUSD=X", timeframe="1d", data_source="test")
    metrics = report["controls"]["no_trade"]["result"]["metrics"]
    assert metrics["total_return"] == 0.0
    assert metrics["trade_count"] == 0


def test_randomized_control_preserves_positions_and_run_lengths():
    signal = pd.Series([0, 0, 1, 1, 1, -1, -1, 0], dtype=float)
    randomized = baseline.circular_shift(signal, seed=7)
    assert sorted(randomized) == sorted(signal)
    # Circular transitions (including last -> first) are invariant to rotation.
    transitions = lambda s: int(np.count_nonzero(s.to_numpy() != np.roll(s.to_numpy(), 1)))
    assert transitions(randomized) == transitions(signal)
    assert randomized.equals(baseline.circular_shift(signal, seed=7))


def test_report_and_atomic_json_are_deterministic(tmp_path):
    args = (_price(), {"test": (_strategy, {"period": 4})}, _ctx())
    first = baseline.build_report(*args, symbol="EURUSD=X", timeframe="1d", data_source="test")
    second = baseline.build_report(*args, symbol="EURUSD=X", timeframe="1d", data_source="test")
    assert first == second
    path = tmp_path / "baseline.json"
    baseline.write_report(first, path)
    bytes_one = path.read_bytes()
    baseline.write_report(second, path)
    assert path.read_bytes() == bytes_one
    assert json.loads(bytes_one)["purpose"] == "research_baseline_controls_only"


def test_baselines_are_not_registered_strategies():
    from strategies.registry import REGISTRY
    assert {"no_trade", "buy_and_hold", "fixed_period_momentum", "sma_crossover"}.isdisjoint(REGISTRY)
