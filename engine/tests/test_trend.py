"""Tests for the Market Trend Intelligence engine (src/trend.py).

Enforces the v1.3 safety spec:
  - direction probabilities sum to 1.0
  - conflicting/weak signals produce an `uncertain` label (encouraged)
  - an invalidation price is ALWAYS returned (required)
  - confidence is low when there is no strategy history
  - regime/direction always come from the allowed vocab
  - NO certainty language appears in reasons/risks
"""
import sys
import re
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import trend


# ---------- fixtures ----------
def _series(vals):
    idx = pd.date_range("2022-01-01", periods=len(vals), freq="D", tz="UTC")
    return pd.Series(vals, index=idx, dtype=float)


def strong_uptrend(n=120):
    rng = np.random.default_rng(1)
    base = np.linspace(100, 140, n) + rng.normal(0, 0.2, n)
    close = _series(base)
    high = close * 1.002
    low = close * 0.998
    return close, high, low


def choppy_range(n=120):
    rng = np.random.default_rng(2)
    base = 100 + np.sin(np.linspace(0, 12, n)) * 0.5 + rng.normal(0, 0.15, n)
    close = _series(base)
    return close, close * 1.001, close * 0.999


def volatile_series(n=120):
    rng = np.random.default_rng(3)
    base = 100 + np.cumsum(rng.normal(0, 2.5, n))
    close = _series(base)
    return close, close * 1.03, close * 0.97


# ---------- probabilities sum to 1 ----------
def test_direction_probabilities_sum_to_one():
    for gen in (strong_uptrend, choppy_range, volatile_series):
        close, high, low = gen()
        snap = trend.build_snapshot(close, high, low, "TEST", "1d")
        p = snap["probabilities"]
        assert abs(sum(p.values()) - 1.0) < 1e-6


# ---------- vocab is constrained ----------
def test_regime_and_direction_in_vocab():
    for gen in (strong_uptrend, choppy_range, volatile_series):
        close, high, low = gen()
        snap = trend.build_snapshot(close, high, low, "TEST", "1d")
        assert snap["regime"] in trend.TREND_REGIMES
        assert snap["direction"] in trend.DIRECTIONS


# ---------- invalidation ALWAYS present (required) ----------
def test_invalidation_always_present():
    for gen in (strong_uptrend, choppy_range, volatile_series):
        close, high, low = gen()
        snap = trend.build_snapshot(close, high, low, "TEST", "1d")
        assert snap["invalidation_price"] is not None
        assert isinstance(snap["invalidation_price"], float)


def test_invalidation_direction_side():
    close, high, low = strong_uptrend()
    inv_bull = trend.invalidation_price("bullish", close, high, low)
    inv_bear = trend.invalidation_price("bearish", close, high, low)
    last = float(close.iloc[-1])
    assert inv_bull < last   # bullish invalidation sits below price
    assert inv_bear > last   # bearish invalidation sits above price


# ---------- uncertain label allowed & encouraged ----------
def test_uncertain_label_emerges_on_conflict():
    # near-random walk with no structure should often be uncertain/range, and
    # crucially must be ALLOWED to be uncertain without error.
    close, high, low = volatile_series()
    snap = trend.build_snapshot(close, high, low, "TEST", "1d")
    assert snap["direction"] in trend.DIRECTIONS
    # the uncertain bucket must exist in the probability distribution
    assert "uncertain" in snap["probabilities"]


def test_conflict_forces_uncertain_direction():
    # directly exercise score_directions with weak trend + high volatility
    probs = trend.score_directions("volatile", trend_strength=0.1,
                                   momentum_score=0.02, volatility_score=0.9)
    assert probs["uncertain"] >= 0.30
    assert trend.dominant_direction(probs) == "uncertain"


# ---------- confidence low without history ----------
def test_confidence_low_without_history():
    conf, best, risks = trend.assign_confidence(
        "trend", "bullish", 0.6, 0.5, 0.3, history=None)
    assert conf <= 0.3
    assert best == "n/a"
    assert any("no comparable strategy history" in r for r in risks)


def test_confidence_higher_with_history():
    hist = {"strategy": "ema_crossover", "win_rate": 0.6, "robustness": 0.8, "sample": 60}
    conf_h, best_h, _ = trend.assign_confidence("trend", "bullish", 0.6, 0.5, 0.3, history=hist)
    conf_n, _, _ = trend.assign_confidence("trend", "bullish", 0.6, 0.5, 0.3, history=None)
    assert conf_h > conf_n
    assert best_h == "ema_crossover"


# ---------- NO certainty language ----------
CERTAINTY = re.compile(
    r"\b(guarantee|guaranteed|certain|certainly|definitely|surely|will\s+(rise|fall|go|reach)|"
    r"100%|no\s+risk|risk[- ]free|sure\s+thing|always\s+wins?)\b", re.IGNORECASE)


def test_no_certainty_language_in_outputs():
    for gen in (strong_uptrend, choppy_range, volatile_series):
        close, high, low = gen()
        snap = trend.build_snapshot(close, high, low, "TEST", "1d")
        blob = " ".join(snap["reasons"] + snap["risks"])
        assert not CERTAINTY.search(blob), f"certainty language found: {blob}"


def test_no_certainty_language_in_source():
    src = (Path(__file__).parent.parent / "src" / "trend.py").read_text()
    # the source may mention the words in comments about NOT claiming certainty,
    # but must not emit them as user-facing strings like "will rise"/"guaranteed".
    for bad in ("will rise", "will fall", "guaranteed", "risk-free", "100% ", "sure thing"):
        assert bad not in src.lower()


# ---------- no live execution in the trend engine ----------
def test_trend_engine_has_no_execution_code():
    for fn in ("src/trend.py", "run_trends.py"):
        txt = (Path(__file__).parent.parent / fn).read_text()
        for bad in ("place_order", "execute_trade", "broker", "position_size",
                    "create_order", "submit_order"):
            assert bad not in txt, f"{fn} contains forbidden token: {bad}"


# ---------- snapshot shape completeness ----------
def test_snapshot_has_all_required_fields():
    close, high, low = strong_uptrend()
    snap = trend.build_snapshot(close, high, low, "EURUSD", "1d")
    for field in ("symbol", "timeframe", "regime", "direction", "trend_strength",
                  "momentum_score", "volatility_score", "confidence_score",
                  "best_strategy", "invalidation_price", "reasons", "risks"):
        assert field in snap
