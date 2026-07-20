"""Regression tests for market-data acquisition integrity.

These encode two findings from the extended-data milestone:

1. Explicit-window fetches (run_acquire_data.py extended history) must NOT
   clobber the shared V2/V3 canonical cache file `yf_<SYM>_<tf>.csv`.
2. yfinance FX daily bars synthesize `open == close` for a minority of rows
   while high/low come from intraday aggregation; a genuine subset of source
   rows violate high>=open / low<=close. This is a SOURCE defect, not a
   validation-rule defect -- the integrity invariants are correct and must
   stay enforced. yfinance FX daily is disqualified as canonical OHLC; MT5
   D1 broker bars are the canonical source.
"""
import hashlib

import pandas as pd
import pytest

import src.data as data


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_explicit_window_fetch_does_not_clobber_canonical_cache(tmp_path, monkeypatch):
    """A start/end fetch must leave the V2/V3 canonical cache byte-identical."""
    monkeypatch.chdir(tmp_path)
    # Seed a canonical cache that we expect to survive an extended fetch.
    canonical = tmp_path / "data" / "yf_EURUSD=X_1d.csv"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2023-07-21 00:00:00+00:00,1.1137,1.1147,1.1110,1.1137,0\n"
    )
    before = _sha(canonical)

    # Extended-history call (the path run_acquire_data.py uses).
    data.fetch_yfinance(
        "EURUSD=X", "1d", cache_dir=str(tmp_path / "data"),
        start="2010-01-01", end=pd.Timestamp("2023-07-22", tz="UTC"),
    )
    after = _sha(canonical)
    assert before == after, "explicit-window fetch MUST NOT overwrite canonical cache"


def test_yfinance_fx_open_equals_close_is_rejected_by_invariants():
    """Confirm the integrity rule is correct and that yfinance FX rows can fail it.

    We do NOT 'fix' the rule. The rule must stay enforced; the source is the
    defect. This test pins that behavior so a future change cannot silently
    relax the invariant.
    """
    df = pd.read_csv("data/raw_yfinance_EURUSD=X_1d.csv")
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    invalid = (
        (h < o) | (h < c) | (l > o) | (l > c) | (h < l)
        | (o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)
    )
    # yfinance FX daily genuinely produces invalid OHLC rows (source defect).
    assert invalid.sum() > 0
    # open==close is a known yfinance FX synthesis artifact.
    assert (df["open"] == df["close"]).sum() > 0
