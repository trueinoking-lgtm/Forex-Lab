"""Regression test: mt5_history_export.py must be standalone on the Windows PC.

It must run with ONLY the Python stdlib, pandas, and MetaTrader5 -- no imports
from engine-local modules (run_acquire_data.py, src/*). Copying just the single
file into an isolated directory and invoking --help must succeed (exit 0) without
any engine context present.
"""
import os
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

EXPORTER = os.path.join(os.path.dirname(__file__), "..", "mt5_history_export.py")


@pytest.fixture(scope="module")
def exporter_module():
    spec = importlib.util.spec_from_file_location("mt5_history_export", EXPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not os.path.exists(EXPORTER),
    reason="exporter not present in this checkout",
)
def test_exporter_is_standalone_via_help():
    """Copy ONLY the exporter into an empty dir and run --help."""
    tmp = tempfile.mkdtemp()
    try:
        dest = os.path.join(tmp, "mt5_history_export.py")
        shutil.copy(EXPORTER, dest)
        # No run_acquire_data.py / src/ present in tmp -- exactly the Windows PC case.
        assert not os.path.exists(os.path.join(tmp, "run_acquire_data.py"))
        assert not os.path.exists(os.path.join(tmp, "src"))
        r = subprocess.run(
            [sys.executable, dest, "--help"],
            cwd=tmp, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"--help failed: {r.stderr}"
        assert "ModuleNotFoundError" not in r.stderr
        assert "run_acquire_data" not in r.stderr
        assert "usage:" in r.stdout.lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_exporter_has_no_engine_local_imports():
    """Static guard: the source must not import run_acquire_data or src.*."""
    src = open(EXPORTER, encoding="utf-8").read()
    assert "from run_acquire_data" not in src
    assert "import run_acquire_data" not in src
    assert "from src" not in src
    assert "import src" not in src


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2010-01-01", pd.Timestamp("2010-01-01", tz="UTC")),
        (datetime(2010, 1, 1), pd.Timestamp("2010-01-01", tz="UTC")),
        (datetime(2010, 1, 1, tzinfo=timezone.utc), pd.Timestamp("2010-01-01", tz="UTC")),
        (datetime(2010, 1, 1, tzinfo=timezone(-timedelta(hours=5))),
         pd.Timestamp("2010-01-01 05:00", tz="UTC")),
    ],
)
def test_as_utc_timestamp(exporter_module, value, expected):
    result = exporter_module.as_utc_timestamp(value)
    assert result == expected
    assert str(result.tz) == "UTC"


def test_normalize_rates_filters_utc_bounds_and_incomplete_candle(exporter_module):
    rates = [
        {"time": int(pd.Timestamp(ts).timestamp()), "open": 1, "high": 2,
         "low": 0.5, "close": 1.5, "tick_volume": 10}
        for ts in ["2010-01-01T04:59:59Z", "2010-01-01T05:00:00Z", "2010-01-02T00:00:00Z"]
    ]

    frame = exporter_module.normalize_rates(
        rates,
        datetime(2010, 1, 1, tzinfo=timezone(-timedelta(hours=5))),
        datetime(2010, 1, 2, tzinfo=timezone.utc),
    )

    assert list(frame.index) == [pd.Timestamp("2010-01-01T05:00:00Z")]


def test_export_default_end_is_current_utc_midnight(exporter_module, monkeypatch, tmp_path):
    expected_end = pd.Timestamp.now(tz="UTC").normalize()

    class Account:
        company = "Test Broker"
        server = "Demo"

    class FakeMT5:
        TIMEFRAME_D1 = 1

        @staticmethod
        def initialize():
            return True

        @staticmethod
        def account_info():
            return Account()

        @staticmethod
        def copy_rates_range(symbol, timeframe, start, end):
            assert symbol == "EURUSD"
            assert timeframe == 1
            assert pd.Timestamp(end) == expected_end
            candle = expected_end - pd.Timedelta(days=1)
            return [{"time": int(candle.timestamp()), "open": 1, "high": 2,
                     "low": 0.5, "close": 1.5, "tick_volume": 10}]

        @staticmethod
        def shutdown():
            pass

    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeMT5)
    output = tmp_path / "rates.csv"
    _, manifest = exporter_module.export(end=None, output=output)

    assert manifest["requested_end"] == expected_end.isoformat()


def test_export_h1_uses_closed_hour_and_h1_manifest(exporter_module, monkeypatch, tmp_path):
    expected_end = pd.Timestamp.now(tz="UTC").floor("h")

    class Account:
        company = "Test Broker"
        server = "Demo"

    class FakeMT5:
        TIMEFRAME_D1 = 1
        TIMEFRAME_H1 = 60

        @staticmethod
        def initialize(): return True
        @staticmethod
        def account_info(): return Account()
        @staticmethod
        def copy_rates_range(symbol, timeframe, start, end):
            assert (symbol, timeframe) == ("GBPUSD", 60)
            assert pd.Timestamp(end) == expected_end
            candle = expected_end - pd.Timedelta(hours=1)
            return [{"time": int(candle.timestamp()), "open": 1, "high": 2,
                     "low": .5, "close": 1.5, "tick_volume": 10}]
        @staticmethod
        def shutdown(): pass

    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeMT5)
    output = tmp_path / "raw_mt5_GBPUSD_1h.csv"
    _, manifest = exporter_module.export(output=output, symbol="GBPUSD", timeframe="H1")
    assert manifest["timeframe"] == "1h"
    assert manifest["symbol"] == "GBPUSD"
    assert manifest["requested_end"] == expected_end.isoformat()
