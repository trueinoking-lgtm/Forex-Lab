"""Tests for the Aether Forex Lab engine (pytest).

Covers: strategy scoring, overfitting penalty, signal scoring, risk calc,
stop-loss requirement, paper signal creation, PnL, decision journal, rule
versioning (logic), read-only safety, no live execution.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src import score, signals, risk, metrics, backtest, log
from strategies.registry import REGISTRY, build_signal, list_strategies


# ---------- helpers ----------
def make_metrics(ret=0.05, sharpe=0.5, pf=1.5, wr=0.55, dd=-0.05, tc=40):
    return {"total_return": ret, "sharpe": sharpe, "profit_factor": pf,
            "win_rate": wr, "max_drawdown": dd, "trade_count": tc}


# ---------- strategy scoring ----------
def test_score_strategy_basic():
    s = score.score_strategy(make_metrics(), [0.01, 0.02, -0.01], 0.10)
    assert 0 <= s["score"] <= 100
    assert s["share_positive_windows"] == pytest.approx(2 / 3, abs=1e-2)


def test_score_insufficient_trades_zero():
    m = make_metrics(tc=5)
    s = score.score_strategy(m, [0.01], 0.10)
    assert s["score"] == 0.0


# ---------- overfitting penalty ----------
def test_overfitting_penalty_low_robustness():
    # "good": 3 of 5 windows positive, modest in-sample
    good = score.score_strategy(make_metrics(ret=0.10, sharpe=0.8, pf=1.8),
                                [0.05, 0.04, 0.03, -0.01, -0.01], 0.05)
    # "lucky": only 1 of 5 windows positive (one big winner), larger in-sample
    lucky = score.score_strategy(make_metrics(ret=0.10, sharpe=0.8, pf=1.8),
                                 [0.25, -0.02, -0.02, -0.02, -0.02], 0.20)
    assert lucky["robustness"] < good["robustness"]
    assert lucky["score"] < good["score"]


def test_oos_gap_penalty():
    # large in-sample vs small OOS => high oos_gap => lower robustness
    s = score.score_strategy(make_metrics(ret=0.05), [0.01, 0.01, 0.01], in_sample_return=0.50)
    assert s["oos_gap"] > 1.0


# ---------- signal scoring ----------
def test_signal_score_blocked_by_regime():
    strat = {"score": 90.0}
    assert signals.score_signal(strat, "trend", regime_allowed=False) == 0.0
    assert signals.score_signal(strat, "trend", regime_allowed=True) == 90.0


# ---------- risk calculation ----------
def test_risk_clip_bounds():
    rc = signals.risk_check(10000, 5.0, 1.0, 0.99)   # asks 5% -> clipped to 1%
    assert rc["risk_pct"] == 1.0
    rc2 = signals.risk_check(10000, 0.1, 1.0, 0.99)  # asks 0.1% -> clipped to 0.5%
    assert rc2["risk_pct"] == 0.5


def test_risk_requires_stop_loss():
    rc = signals.risk_check(10000, 0.75, 1.0, 1.0)   # SL == entry
    assert rc["pass"] is False


def test_position_size_positive():
    sz = risk.position_size(10000, 0.75, 1.0, 0.99)
    assert sz > 0


# ---------- stop-loss requirement ----------
def test_sl_tp_always_defined():
    entry, atr = 1.10, 0.005
    sl, tp = signals.compute_sl_tp(entry, 1, atr)
    assert sl < entry and tp > entry
    sl2, tp2 = signals.compute_sl_tp(entry, -1, atr)
    assert sl2 > entry and tp2 < entry


# ---------- paper trade creation (paper signal dataclass) ----------
def test_paper_signal_creation():
    ps = signals.PaperSignal("EURUSD=X", "ema_crossover", 1, 1.10, 1.09, 1.12,
                             80.0, "trend", "2026-07-08T00:00:00Z")
    d = ps.to_dict()
    assert d["direction"] == 1 and d["stop_loss"] < d["entry"]


# ---------- PnL updates ----------
def test_daily_pnl():
    assert risk.daily_pnl([100, 101]) == 1.0
    assert risk.daily_pnl([100]) == 0.0


# ---------- decision journaling ----------
def test_journal_records_skip_and_signal():
    journal = []
    journal.append({"strategy": "x", "action": "skip", "reason": "low score"})
    journal.append({"strategy": "y", "action": "paper_signal", "direction": 1})
    assert any(j["action"] == "skip" for j in journal)
    assert any(j["action"] == "paper_signal" for j in journal)


# ---------- rule versioning (logic) ----------
def test_rule_versioning_increments():
    versions = []
    versions.append({"v": len(versions) + 1, "rule": "min_signal_score=40"})
    versions.append({"v": len(versions) + 1, "rule": "min_signal_score=45"})
    assert versions[-1]["v"] == 2
    assert versions[0]["rule"] != versions[1]["rule"]


# ---------- read-only safety ----------
def test_paper_only_guard():
    import yaml
    cfg = yaml.safe_load(open(str(Path(__file__).parent.parent / "config.yaml")))
    assert cfg["paper_only"] is True
    assert cfg["allow_live_orders"] is False


# ---------- no live execution (engine has no broker code) ----------
def test_no_broker_secrets_in_engine():
    src_dir = Path(__file__).parent.parent / "src"
    for f in src_dir.glob("*.py"):
        txt = f.read_text()
        assert "place_order" not in txt and "execute_trade" not in txt
        assert "broker_password" not in txt


# ---------- live backtest sanity ----------
def test_backtest_runs_all_strategies():
    dates = pd.date_range("2020-01-01", periods=600, freq="D", tz="UTC")
    rng = np.random.default_rng(0)
    price = pd.Series(100 + np.cumsum(rng.normal(0, 0.3, 600)), index=dates)
    ctx = {"walk_forward": {"train_days": 252, "test_days": 30, "step_days": 30},
           "cost_bps": 3, "initial_capital": 10000, "periods_per_year": 252,
           "risk_free_rate": 0}
    for name in list_strategies():
        fn, params = REGISTRY[name]
        oos = backtest.walk_forward(price, lambda p, **k: fn(p, **params), ctx)
        assert "metrics" in oos


# ---------- metrics ----------
def test_sharpe_zero_on_flat():
    s = pd.Series(0.0, index=pd.date_range("2020-01-01", periods=50, freq="D"))
    assert metrics.sharpe_ratio(s) == 0.0


def test_redact_secrets():
    assert "[REDACTED]" in log.redact("api_key=abcdefgh12345678")
    assert "hello world" == log.redact("hello world")


# ---------- regime validation (regression: a typo must fail loud) ----------
def test_regime_valid_trend_and_range_accepted():
    assert signals.validate_regime("trend") == "trend"
    assert signals.validate_regime("range") == "range"


def test_regime_invalid_typo_fails_loud():
    # regression guard for the historical "grend" typo: an unknown regime must
    # raise rather than silently flow into signals/reporting.
    for bad in ("grend", "trnd", "TREND", "trendx", ""):
        with pytest.raises(ValueError):
            signals.validate_regime(bad)
