"""Tests for the tradeability watcher (safe, scheduled, no-order).

These tests prove the watcher's core safety + dedupe behaviour without ever
touching a real broker:
  * no Signal row when all strategies fail to qualify
  * a qualifying signal is persisted exactly once
  * duplicate notifications are suppressed
  * overlapping execution is prevented by the process lock
  * a complete tradeable cycle never calls place-demo-order (fake broker)
  * the same closed candle is not re-signalled (signal-level dedup)
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import sqlite3
import types
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ENGINE))

import run_execution
from src import data as data_mod
from src.signal_eval import evaluate_strategies
from tradeability_watcher import (
    atomic_write_json, run_cycle, _fingerprint, build_notifier, LogNotifier,
    load_state, STATE_PATH, RESULT_PATH,
)

SYMBOL = "EURUSD=X"


# --------------------------------------------------------------------------- #
# Fixtures: temp DB with a Signal table, controllable market data, fake broker
# --------------------------------------------------------------------------- #
@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    dbp = tmp_path / "forex_lab.db"
    con = sqlite3.connect(dbp)
    con.execute(
        """CREATE TABLE Signal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL, strategy TEXT NOT NULL, direction INTEGER,
            entry REAL, stop_loss REAL, take_profit REAL, signal_score REAL,
            regime TEXT, units REAL, generated_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending', original_signal_id INTEGER,
            UNIQUE(pair, strategy, generated_at))"""
    )
    con.execute(
        """CREATE TABLE ExecutionControl (
            id INTEGER PRIMARY KEY, kill_switch INTEGER DEFAULT 0,
            broker_mode TEXT DEFAULT 'demo', max_open_demo_trades INTEGER DEFAULT 5,
            max_open_per_broker INTEGER DEFAULT 5, execution_mode TEXT DEFAULT 'observe_only',
            primary_demo_broker TEXT DEFAULT 'oanda_practice')"""
    )
    con.execute("INSERT INTO ExecutionControl (id) VALUES (1)")
    con.execute(
        """CREATE TABLE DemoExecutionOrder (
            id INTEGER PRIMARY KEY, signal_id INTEGER, broker TEXT, status TEXT,
            strategy TEXT, symbol TEXT, entry REAL, stop_loss REAL, units REAL,
            deal_id TEXT, position_id TEXT, type_filling_used TEXT, partial INTEGER,
            filled_units REAL)"""
    )
    con.commit()
    con.close()
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    yield dbp


def _make_prices(close=1.1000, direction=1, n=300):
    """Build a minimal OHLC frame; direction shapes the last close move."""
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2024-01-01", periods=n, freq="30min", tz="UTC")
    base = np.linspace(1.0900, close, n)
    close_s = pd.Series(base, index=idx)
    # make the last bar agree with direction so a strategy fires
    if direction > 0:
        close_s.iloc[-1] = close_s.iloc[-1] * 1.001
    else:
        close_s.iloc[-1] = close_s.iloc[-1] * 0.999
    high = close_s + 0.002
    low = close_s - 0.002
    return pd.DataFrame({"open": close_s, "high": high, "low": low, "close": close_s})


@pytest.fixture
def market_all_fail(monkeypatch):
    """A flat/sideways market where no strategy produces a tradeable signal."""
    df = _make_prices(close=1.1000, direction=0)
    monkeypatch.setattr(data_mod, "load_pair", lambda *a, **k: df)


@pytest.fixture
def market_tradeable(monkeypatch):
    """A market where ema_crossover naturally qualifies (score>=40, PF>=1.3...)."""
    df = _make_prices(close=1.1050, direction=-1)
    monkeypatch.setattr(data_mod, "load_pair", lambda *a, **k: df)


@pytest.fixture
def fake_eval_tradeable(monkeypatch):
    """Inject a controlled evaluate_strategies result: ema_crossover qualifies."""
    candle = "2024-01-01T00:00:00+00:00"
    ev = {
        "regime": "trend", "adx": 30.0, "close": 1.1050, "candle_ts": candle,
        "strategies": [
            {"strategy": "ema_crossover", "direction": -1, "entry": 1.1050,
             "stop_loss": 1.1150, "take_profit": 1.0900, "signal_score": 61.0,
             "regime": "trend", "units": 6000.0, "tradeable": True,
             "reasons": ["ok"], "gate_reasons": []},
            {"strategy": "rsi_mean_reversion", "direction": 0, "tradeable": False,
             "reasons": ["flat signal at close"], "gate_reasons": ["flat"]},
        ],
        "best": {"strategy": "ema_crossover", "direction": -1, "entry": 1.1050,
                 "stop_loss": 1.1150, "take_profit": 1.0900, "signal_score": 61.0,
                 "regime": "trend", "units": 6000.0, "tradeable": True,
                 "reasons": ["ok"], "gate_reasons": []},
    }
    monkeypatch.setattr("tradeability_watcher.evaluate_strategies", lambda *a, **k: ev)
    # run_cycle loads market data before calling the evaluator. Keep this safety
    # test wholly offline and independent of the production yfinance cache.
    monkeypatch.setattr(data_mod, "load_pair", lambda *a, **k: _make_prices())
    return ev


@pytest.fixture
def fake_scores(tmp_path, monkeypatch):
    """Backtest scores that make ema_crossover tradeable, others not."""
    scores = {
        "ema_crossover": {"strategy": "ema_crossover", "score": 61.0,
                          "robustness": 0.7, "oos_return": 0.05, "profit_factor": 1.5,
                          "total_return": 0.10},
        "ema_trend_pullback": {"strategy": "ema_trend_pullback", "score": 10.0,
                               "robustness": 0.1, "oos_return": -0.02, "profit_factor": 0.9},
        "rsi_mean_reversion": {"strategy": "rsi_mean_reversion", "score": 20.0,
                               "robustness": 0.2, "oos_return": 0.0, "profit_factor": 1.0},
        "macd_trend_confirmation": {"strategy": "macd_trend_confirmation", "score": 15.0,
                                     "robustness": 0.1, "oos_return": -0.01, "profit_factor": 0.8},
        "london_breakout": {"strategy": "london_breakout", "score": 5.0,
                            "robustness": 0.0, "oos_return": -0.05, "profit_factor": 0.7},
    }
    p = tmp_path / "backtest_EURUSD=X.json"
    p.write_text(json.dumps({"results": list(scores.values())}))
    # The watcher uses a fixed relative result path. Inject the intended fixture
    # scores rather than accidentally reading a repository artifact.
    monkeypatch.setattr("tradeability_watcher.load_scores", lambda *a, **k: scores)
    return p


class FakeBroker:
    """Fake broker: get_account/get_prices/dry-run are benign; place_demo_order
    RAISES. It also intercepts the dry-run command's direct requests.* calls so a
    complete tradeable cycle runs for real against the fake (no network, no real
    order)."""
    def __init__(self, monkeypatch):
        self.calls = []
        self._mp = monkeypatch
        import requests
        self._real_post = requests.post
        self._real_get = requests.get
        # Point the engine's bridge URL at the fake and route requests to us.
        monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://fake.tld")
        monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "fake-token")
        monkeypatch.setattr(requests, "post", self._fake_post)
        monkeypatch.setattr(requests, "get", self._fake_get)

    def _fake_response(self, payload):
        import types as _t
        return _t.SimpleNamespace(status_code=200, json=lambda: payload,
                                  text=json.dumps(payload))

    def _fake_get(self, url, **kw):
        self.calls.append("get:" + url.split("//", 1)[-1])
        if url.rstrip("/").endswith("/account"):
            return self._fake_response({"balance": 100000.0, "currency": "USD"})
        if url.rstrip("/").endswith("/quote"):
            return self._fake_response({"symbol": "EURUSD", "bid": 1.10490,
                                         "ask": 1.10500, "spread": 0.00003})
        return self._fake_response({})

    def _fake_post(self, url, **kw):
        self.calls.append("post:" + url.split("//", 1)[-1])
        if url.rstrip("/").endswith("/dry-run"):
            return self._fake_response({
                "broker": "mt5_demo", "broker_mode": "demo", "would_place": True,
                "dry_run": True, "demo_autotrade_enabled": True,
                "bridge_kill_switch": False, "live_entry": 1.10500,
                "note": "no order placed"})
        # Any other POST (e.g. /place-demo-order) must NOT happen.
        raise AssertionError(f"WATCHER POSTED TO {url} — MUST NOT PLACE ORDERS")

    def get_account(self):
        self.calls.append("get_account")
        return types.SimpleNamespace(balance=100000.0, currency="USD")

    def get_prices(self, symbol):
        self.calls.append("get_prices")
        return types.SimpleNamespace(bid=1.10490, ask=1.10500, spread=0.00003,
                                     timestamp="2024-01-01T00:00:00+00:00")

    def place_demo_order(self, *a, **k):
        raise AssertionError("WATCHER CALLED place_demo_order — MUST NOT HAPPEN")

    def dry_run(self, *a, **k):
        self.calls.append("dry_run")
        return types.SimpleNamespace(status_code=200, json=lambda: {
            "broker": "mt5_demo", "broker_mode": "demo", "would_place": True,
            "dry_run": True})


@pytest.fixture
def fake_broker(monkeypatch):
    fb = FakeBroker(monkeypatch)
    monkeypatch.setattr(run_execution, "build_adapter", lambda *a, **k: fb)
    monkeypatch.setattr(run_execution, "_remote_mt5_adapter", lambda: fb)
    return fb


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr("tradeability_watcher.STATE_PATH", tmp_path / "watcher_state.json")
    monkeypatch.setattr("tradeability_watcher.RESULT_PATH", tmp_path / "watcher_last_result.json")
    monkeypatch.setattr("tradeability_watcher.LOCK_PATH", tmp_path / ".watcher.lock")
    monkeypatch.setattr("tradeability_watcher.DISABLE_FLAG", tmp_path / ".watcher.disabled")
    yield


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_no_signal_when_all_fail(tmp_db, market_all_fail, fake_scores, fake_broker,
                                 monkeypatch):
    monkeypatch.setattr(
        "tradeability_watcher.load_scores",
        lambda *a, **k: {
            name: {"strategy": name, "score": 0.0, "robustness": 0.0,
                   "oos_return": -0.01, "profit_factor": 0.0}
            for name in (
                "ema_crossover", "ema_trend_pullback", "rsi_mean_reversion",
                "macd_trend_confirmation", "london_breakout",
            )
        },
    )
    notifier = LogNotifier()
    res = run_cycle(notifier, dry_adapter=fake_broker)
    assert res["tradeable"] is False
    assert res["signal_created"] is False
    db = sqlite3.connect(str(tmp_db))
    n = db.execute("SELECT COUNT(*) c FROM Signal").fetchone()[0]
    assert n == 0, "no Signal row must be created when nothing qualifies"


def test_qualifying_signal_persisted_once(tmp_db, fake_eval_tradeable, fake_scores, fake_broker):
    notifier = LogNotifier()
    res = run_cycle(notifier, dry_adapter=fake_broker)
    assert res["tradeable"] is True
    assert res["signal_created"] is True
    db = sqlite3.connect(str(tmp_db))
    rows = db.execute("SELECT * FROM Signal").fetchall()
    assert len(rows) == 1, "exactly one Signal row for the qualifying candle"
    assert rows[0][2] == res["strategy"]  # strategy is column index 2
    # generated_at must be set (fresh), and a source candle ts recorded
    assert res["generated_at"]
    assert res["source_candle_ts"]


def test_duplicate_notifications_suppressed(tmp_db, fake_eval_tradeable, fake_scores, fake_broker):
    notifier = _RecordingNotifier()
    # first cycle: notifies (tradeability_changed false->true)
    run_cycle(notifier, dry_adapter=fake_broker)
    assert notifier.events.count("tradeability_changed") == 1
    # second cycle, identical state: no new notification
    run_cycle(notifier, dry_adapter=fake_broker)
    assert notifier.events.count("tradeability_changed") == 1, "duplicate suppressed"
    # only ONE signal row persisted across both cycles (dedup)
    db = sqlite3.connect(str(tmp_db))
    assert db.execute("SELECT COUNT(*) c FROM Signal").fetchone()[0] == 1


def test_same_candle_not_resignalled(tmp_db, fake_eval_tradeable, fake_scores, fake_broker):
    notifier = LogNotifier()
    r1 = run_cycle(notifier, dry_adapter=fake_broker)
    assert r1["signal_created"] is True
    # Re-run with the SAME candle (data unchanged) -> must NOT create another row
    r2 = run_cycle(notifier, dry_adapter=fake_broker)
    assert r2["signal_created"] is False
    assert r2.get("deduped") is True
    db = sqlite3.connect(str(tmp_db))
    assert db.execute("SELECT COUNT(*) c FROM Signal").fetchone()[0] == 1


def test_overlapping_execution_prevented(tmp_db, fake_eval_tradeable, fake_scores, fake_broker):
    from tradeability_watcher import main as watcher_main
    # Hold the lock file open in this process.
    lockf = open(tmp_db.parent / ".watcher.lock", "w")
    fcntl.flock(lockf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Running main() now must skip (another instance "holds" the lock).
    rc = watcher_main()
    assert rc == 0
    fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
    lockf.close()
    # No signal created because the cycle was skipped.
    db = sqlite3.connect(str(tmp_db))
    assert db.execute("SELECT COUNT(*) c FROM Signal").fetchone()[0] == 0


def test_no_order_endpoint_reachable(tmp_db, fake_eval_tradeable, fake_scores, fake_broker):
    notifier = LogNotifier()
    res = run_cycle(notifier, dry_adapter=fake_broker)
    assert res["tradeable"] is True
    # The fake broker records which methods were called.
    # preflight reachability + dry-run quote (adapter methods):
    assert "get_account" in fake_broker.calls      # preflight reachability
    assert "get_prices" in fake_broker.calls        # dry-run quote
    # dry-run POST went through the intercepted requests layer:
    assert any(c.startswith("post:") and "/dry-run" in c for c in fake_broker.calls)
    # CRITICAL: no placement endpoint was ever reached.
    assert not any("place-demo-order" in c for c in fake_broker.calls), "NEVER place an order"
    assert "place_demo_order" not in fake_broker.calls, "NEVER call place_demo_order"
    # Saved result must reflect dry-run, not placement.
    dry = res.get("dry_run") or {}
    raw = json.dumps(dry)
    assert "dry_run" in raw and "would_place" in raw
    assert "placed_order" not in raw or dry.get("placed_order") in (False, None)


def test_atomic_write_json_permissions(tmp_path):
    p = tmp_path / "x.json"
    atomic_write_json(p, {"a": 1})
    assert p.exists()
    mode = oct(p.stat().st_mode & 0o777)
    assert mode == "0o600", f"expected 0600, got {mode}"


def test_fingerprint_distinguishes_candles():
    fp1 = _fingerprint("EURUSD", "ema_crossover", 1, "2024-01-01T00:00:00+00:00")
    fp2 = _fingerprint("EURUSD", "ema_crossover", 1, "2024-01-01T00:30:00+00:00")
    fp3 = _fingerprint("EURUSD", "ema_crossover", -1, "2024-01-01T00:00:00+00:00")
    assert fp1 != fp2
    assert fp1 != fp3


class _RecordingNotifier(LogNotifier):
    def __init__(self):
        super().__init__()
        self.events = []

    def notify(self, event, payload):
        self.events.append(event)
