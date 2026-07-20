import importlib.util
from pathlib import Path

import pandas as pd

ENGINE = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("cross_source_v3", ENGINE / "run_cross_source_v3.py")
cross = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(cross)


def test_load_source_normalizes_utc_and_fingerprint_is_deterministic(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("timestamp,open,high,low,close,volume\n2020-01-02,1,2,.5,1.5,0\n")
    frame = cross.load_source(path)
    assert str(frame.index.tz) == "UTC"
    assert cross.fingerprint(frame) == cross.fingerprint(frame.copy())


def test_integrity_counts_defective_ohlc(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("timestamp,open,high,low,close,volume\n2020-01-02,1,1.1,.9,1.2,0\n")
    frame = cross.load_source(path)
    finding = cross.integrity(frame, path)
    assert finding["invalid_ohlc_count"] == 1


def test_definitions_contain_baseline_strategies_and_controls():
    # The five frozen baseline strategies + five controls remain the comparison
    # set. Research strategies (e.g. trend_continuation) may be added without
    # breaking this assertion, so check the baseline five are present as a subset
    # rather than asserting an exact registry size.
    baseline_strategies = {
        "ema_crossover", "ema_trend_pullback", "rsi_mean_reversion",
        "macd_trend_confirmation", "london_breakout",
    }
    defs = cross.definitions()
    assert baseline_strategies.issubset(set(cross.REGISTRY))
    assert len(defs) >= 10
    assert set(cross.REGISTRY).issubset(defs)
