import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.live_readiness import readiness_report
from src.validation import directional_accuracy, held_out_validate


def _ctx():
    return {"cost_bps": 0, "initial_capital": 10000, "periods_per_year": 252,
            "risk_free_rate": 0, "walk_forward": {"train_days": 60,
            "test_days": 30, "step_days": 30}}


def _signal(price):
    return pd.Series(1.0, index=price.index)


def test_held_out_refuses_short_future():
    price = pd.Series(range(1, 121), index=pd.date_range("2024-01-01", periods=120, tz="UTC"))
    with pytest.raises(ValueError, match="not enough held-out future data"):
        held_out_validate(price, _signal, _ctx(), price.index[-30])


def test_held_out_accepts_clean_split_and_returns_metrics():
    price = pd.Series(range(100, 300), index=pd.date_range("2024-01-01", periods=200, tz="UTC"))
    result = held_out_validate(price, _signal, _ctx(), price.index[100])
    assert result["n"] == 100
    assert "total_return" in result["metrics"]
    assert len(result["equity"]) == 100


def test_directional_accuracy_profitable_and_empty():
    result = directional_accuracy([{"pnl": 3, "reason": "series_end"},
                                   {"pnl": -1, "reason": "stop_loss"}])
    assert result["hit_rate"] > 0
    assert result["series_end_hits"] == 1
    assert directional_accuracy([])["hit_rate"] == 0
    assert directional_accuracy([])["n"] == 0


def _report(**changes):
    values = {"walk_forward_score": 50, "robustness": .4, "oos_return": .1,
              "held_out_metrics": {"total_return": .1, "max_drawdown": -.04,
                                   "profit_factor": 1.5},
              "directional_accuracy": {"hit_rate": .6}}
    values.update(changes)
    return readiness_report(**values)


def test_readiness_good_and_bad():
    assert _report()["go"] is True
    assert _report(oos_return=0)["go"] is False
    assert _report(directional_accuracy={"hit_rate": .49})["go"] is False


def test_readiness_nan_profit_factor_fails_closed():
    assert _report(held_out_metrics={"total_return": .1, "max_drawdown": -.04,
                                    "profit_factor": float("nan")})["go"] is False
    assert _report(held_out_metrics={"total_return": .1, "max_drawdown": -.04,
                                    "profit_factor": float("inf")})["go"] is True
