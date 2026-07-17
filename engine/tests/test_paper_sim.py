import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.paper_sim import metrics_from_returns, overfitting_flags, simulate


def test_simulate_uptrend_hits_take_profit():
    index = pd.date_range("2025-01-01", periods=8, freq="D", tz="UTC")
    price = pd.Series([100, 101, 102, 103, 104, 105, 106, 107], index=index)
    signal = {"symbol": "TEST", "side": "buy", "entry": 100, "stop_loss": 99,
              "take_profit": 104, "units": 1, "timestamp": str(index[0]),
              "tradeable": True}
    result = simulate([signal], price, cost_bps=0)
    assert result["trades"][0]["reason"] == "take_profit"
    assert result["metrics"]["trade_count"] == 1
    assert result["metrics"]["profit_factor"] > 0
    assert result["equity_curve"][-1] > result["equity_curve"][0]


def test_overfitting_flags_too_good_metrics():
    metrics = {"sharpe": 4, "profit_factor": 5, "win_rate": 0.9,
               "max_drawdown": 0.01, "return_std": 0.0}
    flags = overfitting_flags(metrics, in_sample_return=1, oos_return=0.1)
    assert len(flags) == 6


def test_metrics_empty_and_all_loss_do_not_crash():
    empty = metrics_from_returns([], [10000])
    assert empty["trade_count"] == 0 and empty["profit_factor"] == 0
    losses = metrics_from_returns([-0.01, -0.02], [10000, 9900, 9702])
    assert losses["profit_factor"] == 0
    wins = metrics_from_returns([0.01], [10000, 10100])
    assert math.isinf(wins["profit_factor"])
