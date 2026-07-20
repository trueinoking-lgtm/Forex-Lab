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


def test_definitions_are_five_strategies_and_five_controls():
    defs = cross.definitions()
    assert len(cross.REGISTRY) == 5
    assert len(defs) == 10
    assert set(cross.REGISTRY).issubset(defs)
