"""Known research-pipeline integrity defects.

These strict xfails document fail-closed behavior that the current implementation
does not yet provide.  They must become ordinary passing tests when the defects
are fixed.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import backtest, data


@pytest.mark.xfail(
    strict=True,
    reason="cache freshness is incorrectly based on the oldest market timestamp",
)
def test_fresh_cache_does_not_require_network(tmp_path, monkeypatch):
    cache = tmp_path / "yf_EURUSD=X_1d.csv"
    old_bars = pd.DataFrame({
        "timestamp": pd.to_datetime(["2023-01-02", "2023-01-03"], utc=True),
        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
        "close": [1.0, 1.0], "volume": [0, 0],
    })
    old_bars.to_csv(cache, index=False)
    now = time.time()
    os.utime(cache, (now, now))

    class NoNetworkExpected:
        @staticmethod
        def download(*args, **kwargs):
            raise AssertionError("a freshly written cache must not require network access")

    monkeypatch.setattr(data, "yf", NoNetworkExpected)
    result = data.fetch_yfinance("EURUSD=X", cache_dir=str(tmp_path))
    assert len(result) == 2


@pytest.mark.xfail(
    strict=True,
    reason="walk-forward permits overlapping test windows and duplicates OOS timestamps",
)
def test_walk_forward_rejects_or_deduplicates_overlapping_oos_windows():
    index = pd.date_range("2024-01-01", periods=18, freq="D", tz="UTC")
    price = pd.Series(range(100, 118), index=index, dtype=float)
    ctx = {
        "walk_forward": {"train_days": 6, "test_days": 6, "step_days": 3},
        "cost_bps": 0.0, "initial_capital": 10_000.0,
        "periods_per_year": 252, "risk_free_rate": 0.0,
    }

    result = backtest.walk_forward(price, lambda observed: observed * 0 + 1, ctx)
    assert result["returns"].index.is_unique
