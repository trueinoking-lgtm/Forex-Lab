import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

try:
    from engine.run_session_breakout_research import (CORE_PAIRS, DEFAULT_PARAMS, aggregate,
        load_h1, research)
except ImportError:
    from run_session_breakout_research import CORE_PAIRS, DEFAULT_PARAMS, aggregate, load_h1, research


def synthetic_h1(pair):
    """Tiny deterministic synthetic fixture: test-only, never research data."""
    idx = pd.date_range("2024-01-01", periods=24*10, freq="h", tz="UTC")
    close = pd.Series(1.1 + np.sin(np.arange(len(idx))/9)*.002, index=idx)
    close[idx.hour == 8] += .004
    return pd.DataFrame({"open": close.shift().fillna(close.iloc[0]), "high": close+.0003,
                         "low": close-.0003, "close": close, "volume": 1}, index=idx)


def test_missing_data_refuses_without_fallback(tmp_path):
    with pytest.raises(FileNotFoundError, match="H1 data required"):
        load_h1("EURUSD", tmp_path)


def test_cli_missing_data_is_explicit_and_writes_no_results(tmp_path):
    script = Path(__file__).parents[1] / "run_session_breakout_research.py"
    run = subprocess.run([sys.executable, str(script), "--data-dir", str(tmp_path)], capture_output=True, text=True)
    assert run.returncode != 0 and "H1 data required" in run.stderr
    assert not list(tmp_path.glob("session_breakout*.json"))


def test_synthetic_fixture_end_to_end_is_nonpersisting_and_scoped():
    frames = {p: synthetic_h1(p) for p in CORE_PAIRS}
    payload = research(frames, synthetic_test_fixture=True, candidates=[DEFAULT_PARAMS])
    assert payload["synthetic_test_fixture"] is True
    assert payload["aggregate_cross_pair_test"]["scope"] == "aggregate_cross_pair_test"
    assert payload["cost_stress"]["scope"] == "cost_stress"
    assert all(x["scope"] == "randomized_control" for x in payload["randomized_control"])
    with pytest.raises(ValueError, match="never persist"):
        research(frames, persist=True, synthetic_test_fixture=True, candidates=[DEFAULT_PARAMS])


def test_aggregate_profit_factor_is_recomputed():
    trades = [{"still_open_at_end": False, "net_pnl": 2., "return_pct": .02,
               "holding_bars": 1}, {"still_open_at_end": False, "net_pnl": -1.,
               "return_pct": -.01, "holding_bars": 1}]
    # lifecycle_metrics consumes these additional fields only for winner concentration.
    for i, t in enumerate(trades): t.update({"exit_ts": "x", "entry_ts": str(i)})
    assert aggregate(trades)["profit_factor"] == 2.0
