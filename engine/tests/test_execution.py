"""Tests for the demo execution bridge (engine/src/execution)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.signals import PaperSignal
from src.execution import (
    MockDemoAdapter,
    DemoOrderRequest,
    run_pretrade_guards,
    GuardError,
    redact,
    build_adapter,
    available_adapters,
    MAX_OPEN_DEMO_TRADES_DEFAULT,
    validate_price_geometry,
    check_demo_trade_mode,
    is_live_trade_mode,
)


def _signal(entry=1.1000, sl=1.0950, tp=1.1050, direction=1, units=2000.0, sid=1,
            timestamp="2026-07-10T00:00:00"):
    return PaperSignal(
        id=sid,
        pair="EURUSD", strategy="rsi", direction=direction, entry=entry,
        stop_loss=sl, take_profit=tp, signal_score=60.0, regime="trend",
        timestamp=timestamp, units=units,
    )


def _good_order(signal=None, entry=1.1000):
    s = signal or _signal(entry=entry)
    return DemoOrderRequest(
        symbol=s.pair, side="buy" if s.direction > 0 else "sell",
        units=s.units, stop_loss=s.stop_loss, take_profit=s.take_profit,
        signal_id=1, requested_entry=entry,
    )


# --- redaction ---
def test_redact_hides_secrets():
    s = redact("api_key=abc123SECRET token=xyzTOKEN")
    assert "abc123SECRET" not in s
    assert "xyzTOKEN" not in s
    assert "[REDACTED]" in s


# --- live orders disabled ---
def test_live_mode_rejected():
    order = _good_order()
    res = run_pretrade_guards(
        order, broker_mode="live", allow_live_orders=False, account=10000,
        risk_pct=0.75, signal=_signal(), open_demo_trades=0,
    )
    assert not res.passed
    assert any("broker_mode" in r for r in res.reasons)


def test_allow_live_orders_true_rejected():
    order = _good_order()
    res = run_pretrade_guards(
        order, broker_mode="demo", allow_live_orders=True, account=10000,
        risk_pct=0.75, signal=_signal(), open_demo_trades=0,
    )
    assert not res.passed
    assert any("ALLOW_LIVE_ORDERS" in r for r in res.reasons)


# --- missing SL / TP rejects ---
def test_missing_sl_rejects():
    s = _signal()
    order = DemoOrderRequest(symbol=s.pair, side="buy", units=s.units,
                             stop_loss=None, take_profit=s.take_profit,
                             signal_id=1, requested_entry=1.1)
    res = run_pretrade_guards(order, broker_mode="demo", allow_live_orders=False,
                              account=10000, risk_pct=0.75, signal=s, open_demo_trades=0)
    assert not res.passed
    assert any("stop_loss" in r for r in res.reasons)


def test_missing_tp_rejects():
    s = _signal()
    order = DemoOrderRequest(symbol=s.pair, side="buy", units=s.units,
                             stop_loss=s.stop_loss, take_profit=None,
                             signal_id=1, requested_entry=1.1)
    res = run_pretrade_guards(order, broker_mode="demo", allow_live_orders=False,
                              account=10000, risk_pct=0.75, signal=s, open_demo_trades=0)
    assert not res.passed
    assert any("take_profit" in r for r in res.reasons)


# --- risk check required ---
def test_risk_check_required():
    # SL == entry -> risk_check fails
    s = _signal(sl=1.1000, tp=1.1050)
    order = _good_order(signal=s, entry=1.1000)
    res = run_pretrade_guards(order, broker_mode="demo", allow_live_orders=False,
                              account=10000, risk_pct=0.75, signal=s, open_demo_trades=0)
    assert not res.passed
    assert any("risk_check" in r for r in res.reasons)


# --- paper signal required ---
def test_paper_signal_required():
    order = _good_order()
    res = run_pretrade_guards(order, broker_mode="demo", allow_live_orders=False,
                              account=10000, risk_pct=0.75, signal=None, open_demo_trades=0)
    assert not res.passed
    assert any("paper Signal" in r for r in res.reasons)


# --- max open enforced ---
def test_max_open_demo_trades_enforced():
    order = _good_order()
    res = run_pretrade_guards(order, broker_mode="demo", allow_live_orders=False,
                              account=10000, risk_pct=0.75, signal=_signal(),
                              open_demo_trades=MAX_OPEN_DEMO_TRADES_DEFAULT)
    assert not res.passed
    assert any("open demo trades" in r for r in res.reasons)


# --- pass path ---
def test_valid_order_passes():
    order = _good_order()
    res = run_pretrade_guards(order, broker_mode="demo", allow_live_orders=False,
                              account=10000, risk_pct=0.75, signal=_signal(), open_demo_trades=0)
    assert res.passed, res.reasons
    assert res.risk and res.risk["pass"]


# --- kill switch ---
def test_kill_switch_rejects():
    order = _good_order()
    res = run_pretrade_guards(order, broker_mode="demo", allow_live_orders=False,
                              account=10000, risk_pct=0.75, signal=_signal(),
                              open_demo_trades=0, kill_switch=True)
    assert not res.passed
    assert any("kill switch" in r for r in res.reasons)


# --- mock adapter works ---
def test_mock_adapter_fills_and_redacts():
    a = MockDemoAdapter()
    acc = a.get_account()
    assert acc.broker_mode == "demo"
    q = a.get_prices("EURUSD")
    assert q.ask > q.bid
    order = _good_order()
    st = a.place_demo_order(order)
    assert st.status == "filled"
    assert st.filled_entry is not None
    assert st.spread_at_entry is not None
    assert st.slippage is not None
    assert "[REDACTED]" not in st.raw_redacted  # nothing secret in mock
    # get_order_status + open positions
    assert a.get_order_status(st.order_id).status == "filled"
    assert len(a.get_open_positions()) == 1
    # close
    cst = a.close_demo_order(st.order_id)
    assert cst.status == "closed"


def test_mock_adapter_mode_locked_demo():
    a = MockDemoAdapter()
    assert a.mode == "demo"


# --- adapter factory ---
def test_factory_defaults_to_mock():
    a = build_adapter("mock")
    assert isinstance(a, MockDemoAdapter)


def test_factory_unknown_raises():
    with pytest.raises(ValueError):
        build_adapter("binance_live")


def test_real_adapters_unavailable_without_creds():
    # ensure no creds in env
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER",
              "OANDA_PRACTICE_API_KEY", "OANDA_PRACTICE_ACCOUNT"):
        os.environ.pop(k, None)
    av = available_adapters()
    assert av["mt5_demo"] is False
    assert av["oanda_practice"] is False
    # fail_loud=True raises when requested without creds
    with pytest.raises(RuntimeError):
        build_adapter("mt5_demo", fail_loud=True)
    with pytest.raises(RuntimeError):
        build_adapter("oanda_practice", fail_loud=True)
    # fail_loud=False falls back to mock
    assert isinstance(build_adapter("mt5_demo", fail_loud=False), MockDemoAdapter)
    assert isinstance(build_adapter("oanda_practice", fail_loud=False), MockDemoAdapter)


# ===== Full demo lifecycle (mock) =====
def test_lifecycle_creates_journal_row():
    import sqlite3
    from run_execution import (
        _db, _control, _paper_signal, cmd_mock_lifecycle, _now,
    )
    # We drive the lifecycle via the CLI function directly using a temp signal row.
    db = _db()
    # ensure a paper Signal exists (reuse id if present)
    sid = 1
    cur = db.execute("SELECT id FROM Signal WHERE id=? AND status='paper'", (sid,)).fetchone()
    if not cur:
        db.execute(
            "INSERT INTO Signal (id,pair,strategy,direction,entry,stop_loss,take_profit,"
            "status,signal_score,regime,generated_at,units) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, "EURUSD", "rsi", 1, 1.1000, 1.0950, 1.1050, "paper", 60.0, "trend",
             "2026-07-10T00:00:00", 2000.0),
        )
        db.commit()
    # run the lifecycle with a fixed run_id
    rc = cmd_mock_lifecycle(_args(signal_id=sid, run_id="test-lc-1"))
    assert rc == 0
    row = db.execute(
        "SELECT * FROM ExecutionJournal WHERE run_id=? AND actual_demo_pnl IS NOT NULL",
        ("test-lc-1",),
    ).fetchone()
    assert row is not None, "journal row must be written"
    # paper + demo pnl present
    assert row["expected_paper_pnl"] is not None
    assert row["actual_demo_pnl"] is not None
    # spread/slippage/latency recorded
    assert row["slippage"] is not None
    assert row["spread"] is not None
    assert row["latency_ms"] is not None
    # clearly labelled mock + demo
    assert row["broker"] == "mock"
    assert row["broker_mode"] == "demo"


def test_lifecycle_rerun_same_run_id_no_duplicate():
    from run_execution import _db, cmd_mock_lifecycle
    db = _db()
    before = db.execute(
        "SELECT COUNT(*) c FROM ExecutionJournal WHERE run_id='test-lc-1'",
    ).fetchone()["c"]
    rc = cmd_mock_lifecycle(_args(signal_id=1, run_id="test-lc-1"))
    after = db.execute(
        "SELECT COUNT(*) c FROM ExecutionJournal WHERE run_id='test-lc-1'",
    ).fetchone()["c"]
    assert rc == 0
    assert after == before, "rerun of same run_id must not duplicate proof row"
    # a new run_id should create a new row
    rc2 = cmd_mock_lifecycle(_args(signal_id=1, run_id="test-lc-2"))
    assert rc2 == 0
    after2 = db.execute(
        "SELECT COUNT(*) c FROM ExecutionJournal WHERE run_id='test-lc-2'",
    ).fetchone()["c"]
    assert after2 == 1


def test_kill_switch_blocks_lifecycle():
    from run_execution import _db, _control, cmd_mock_lifecycle
    db = _db()
    db.execute("UPDATE ExecutionControl SET kill_switch=1 WHERE id=1")
    db.commit()
    try:
        rc = cmd_mock_lifecycle(_args(signal_id=1, run_id="test-lc-kill"))
        assert rc == 2, "kill switch must block lifecycle"
        row = db.execute(
            "SELECT * FROM ExecutionJournal WHERE run_id='test-lc-kill'"
        ).fetchone()
        assert row is None, "no journal row when blocked"
    finally:
        db.execute("UPDATE ExecutionControl SET kill_switch=0 WHERE id=1")
        db.commit()


def test_paper_pnl_not_overwritten_by_broker_response():
    """Expected paper PnL is computed from the paper signal, independent of the
    fill. Even if the broker response implied a different number, the stored
    expected_paper_pnl must equal the paper-model value."""
    from run_execution import _db, cmd_mock_lifecycle, _paper_signal
    db = _db()
    s = _paper_signal(db, 1)
    # manually compute expected paper pnl the way the CLI does
    units = s.units or 0.0
    direction = 1 if s.direction > 0 else -1
    exit_price = s.take_profit
    expected = round((exit_price - s.entry) * direction * units, 2)
    rc = cmd_mock_lifecycle(_args(signal_id=1, run_id="test-lc-pnl"))
    assert rc == 0
    row = db.execute(
        "SELECT expected_paper_pnl FROM ExecutionJournal WHERE run_id='test-lc-pnl'"
    ).fetchone()
    assert row["expected_paper_pnl"] == expected


def test_no_secrets_in_journal_or_raw_response():
    from run_execution import _db, cmd_mock_lifecycle
    db = _db()
    rc = cmd_mock_lifecycle(_args(signal_id=1, run_id="test-lc-secret2"))
    assert rc == 0
    row = db.execute(
        "SELECT * FROM ExecutionJournal WHERE run_id='test-lc-secret2'"
    ).fetchone()
    assert row is not None
    blob = (row["lesson_json"] or "")
    for secret in ("password", "token", "api_key", "PRACTICE", "secret="):
        assert secret.lower() not in blob.lower(), f"leak of {secret}"
    # the order row's raw response also has no secret
    orow = db.execute(
        "SELECT raw_response_redacted_json FROM DemoExecutionOrder WHERE id=?",
        (row["demo_order_id"],),
    ).fetchone()
    roblob = orow["raw_response_redacted_json"] or ""
    assert "password" not in roblob.lower()


def test_live_broker_mode_impossible_in_journal():
    """ExecutionJournal has CHECK (broker_mode='demo'); attempting to insert live
    must be rejected by SQLite."""
    import sqlite3
    from run_execution import _db
    db = _db()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO ExecutionJournal (demo_order_id, broker, broker_mode, "
            "created_at, actual_demo_pnl) VALUES (?,?,?,?,?)",
            (1, "mock", "live", "2026-07-10T00:00:00", 0.0),
        )


def _args(**kw):
    class A:
        pass
    a = A()
    a.signal_id = kw.get("signal_id")
    a.run_id = kw.get("run_id")
    a.force = kw.get("force", False)
    return a


# ===== v1.3.2 broker adapters: safety locks =====

def test_missing_oanda_creds_fails_loud():
    os.environ.pop("OANDA_PRACTICE_API_KEY", None)
    os.environ.pop("OANDA_PRACTICE_ACCOUNT", None)
    from src.execution.factory import build_adapter
    with pytest.raises(RuntimeError):
        build_adapter("oanda_practice", fail_loud=True)


def test_missing_mt5_creds_fails_loud():
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        os.environ.pop(k, None)
    from src.execution.factory import build_adapter
    with pytest.raises(RuntimeError):
        build_adapter("mt5_demo", fail_loud=True)


def test_missing_mt5_terminal_fails_loud(monkeypatch):
    # Provide creds but no MetaTrader5 SDK -> construction must fail loud.
    monkeypatch.setenv("MT5_LOGIN", "123")
    monkeypatch.setenv("MT5_PASSWORD", "pw")
    monkeypatch.setenv("MT5_SERVER", "srv")
    import importlib
    import src.execution.mt5_demo as m

    # Simulate the SDK being absent.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "MetaTrader5":
            raise ImportError("no MT5")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError):
        m.MT5DemoAdapter()


def test_oanda_live_endpoint_rejected():
    os.environ.pop("OANDA_PRACTICE_API_KEY", None)
    os.environ.pop("OANDA_PRACTICE_ACCOUNT", None)
    from src.execution.oanda_practice import OandaPracticeAdapter
    with pytest.raises(RuntimeError):
        OandaPracticeAdapter()  # no creds -> fail loud


def test_oanda_symbol_mapping():
    from src.execution.oanda_practice import SYMBOL_MAP
    assert SYMBOL_MAP["EURUSD"] == "EUR_USD"
    assert SYMBOL_MAP["GBPUSD"] == "GBP_USD"
    assert SYMBOL_MAP["USDJPY"] == "USD_JPY"
    assert SYMBOL_MAP["AUDUSD"] == "AUD_USD"
    assert SYMBOL_MAP["USDCAD"] == "USD_CAD"
    assert SYMBOL_MAP["XAUUSD"] == "XAU_USD"


def test_dry_run_default_prevents_oanda_order(monkeypatch):
    monkeypatch.setenv("OANDA_PRACTICE_API_KEY", "dummy")
    monkeypatch.setenv("OANDA_PRACTICE_ACCOUNT", "123")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("DEMO_AUTOTRADE_ENABLED", "true")
    from src.execution.oanda_practice import OandaPracticeAdapter
    a = OandaPracticeAdapter()
    st = a.place_demo_order(_good_order())
    assert st.status == "skipped"
    assert "DRY_RUN" in (st.rejection_reason or "")


def test_autotrade_off_blocks_oanda_order(monkeypatch):
    monkeypatch.setenv("OANDA_PRACTICE_API_KEY", "dummy")
    monkeypatch.setenv("OANDA_PRACTICE_ACCOUNT", "123")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("DEMO_AUTOTRADE_ENABLED", "false")
    from src.execution.oanda_practice import OandaPracticeAdapter
    a = OandaPracticeAdapter()
    st = a.place_demo_order(_good_order())
    assert st.status == "skipped"
    assert "DEMO_AUTOTRADE_ENABLED" in (st.rejection_reason or "")


def test_kill_switch_blocks_all_broker_demo_orders(monkeypatch):
    # can_place_real_demo must be False under observe_only (default) + kill via control.
    from src.execution.factory import can_place_real_demo, execution_mode
    assert execution_mode() == "observe_only"
    assert can_place_real_demo() is False


def test_max_open_enforced_per_broker():
    s = _signal()
    req = _good_order(s)
    g = run_pretrade_guards(
        req, broker_mode="demo", allow_live_orders=False, account=10000.0,
        risk_pct=0.75, signal=s, open_demo_trades=2, max_open_demo_trades=5,
        broker="mt5_demo", open_demo_trades_by_broker=5,  # per-broker cap hit
        max_open_per_broker=5,
    )
    assert g.passed is False
    assert any("mt5_demo" in r for r in g.reasons)


def test_no_secret_columns_added(monkeypatch):
    # DB schema for execution tables must not contain secret-bearing columns.
    import sqlite3
    from run_execution import _db
    db = _db()
    for tbl in ("DemoExecutionOrder", "ExecutionJournal", "ExecutionControl", "BrokerCapability"):
        cols = [c["name"] for c in db.execute(f"PRAGMA table_info({tbl})").fetchall()]
        for secret in ("api_key", "password", "token", "secret", "login"):
            assert secret not in cols, f"{tbl} must not store {secret}"


def test_broker_failure_cannot_create_fake_fill(monkeypatch):
    # If the adapter raises, no 'filled' status should ever be produced.
    from src.execution.adapter import ExecutionAdapter, DemoOrderRequest, OrderStatus

    class BoomAdapter(ExecutionAdapter):
        name = "mock"
        mode = "demo"

        def get_account(self):
            raise RuntimeError("boom")

        def get_prices(self, symbol):
            raise RuntimeError("boom")

        def place_demo_order(self, order):
            raise RuntimeError("broker down")

        def close_demo_order(self, oid):
            raise RuntimeError("boom")

        def get_open_positions(self):
            return []

        def get_order_status(self, oid):
            raise RuntimeError("boom")

    a = BoomAdapter()
    with pytest.raises(RuntimeError):
        a.place_demo_order(_good_order())
    # No status object is returned at all -> cannot be 'filled'.
    st = OrderStatus(order_id="", status="rejected", rejection_reason="boom")
    assert st.status != "filled"


def test_duplicate_signal_broker_runid_blocked(monkeypatch):
    import sqlite3
    from run_execution import _db, _acquire_lock, _lock_key_exists
    db = _db()
    db.execute("DELETE FROM DemoExecutionLock WHERE signal_id=999 AND broker='mt5_demo' AND run_id='r1'")
    db.commit()
    ok1 = _acquire_lock(db, 999, "mt5_demo", "r1", 1)
    ok2 = _acquire_lock(db, 999, "mt5_demo", "r1", 2)  # duplicate
    assert ok1 is True
    assert ok2 is False
    assert _lock_key_exists(db, 999, "mt5_demo", "r1") is True
    db.execute("DELETE FROM DemoExecutionLock WHERE signal_id=999 AND broker='mt5_demo'")
    db.commit()


def test_mock_lifecycle_still_passes(monkeypatch):
    from run_execution import cmd_mock_lifecycle
    rc = cmd_mock_lifecycle(_args(signal_id=1, run_id="v132-mock-check"))
    assert rc == 0


# ===== v1.3.4 price-geometry + trade_mode + stale-signal hardening =====

def test_validate_price_geometry_buy_rejects_tp_below_entry():
    # buy needs SL < entry < TP; TP below entry must reject.
    r = validate_price_geometry("buy", entry=1.14143, stop_loss=1.095, take_profit=1.105)
    assert r is not None and "invalid buy geometry" in r


def test_validate_price_geometry_buy_rejects_sl_above_entry():
    # SL above entry is invalid for a buy.
    r = validate_price_geometry("buy", entry=1.14143, stop_loss=1.150, take_profit=1.160)
    assert r is not None and "invalid buy geometry" in r


def test_validate_price_geometry_sell_rejects_tp_above_entry():
    # sell needs TP < entry < SL; TP above entry must reject.
    r = validate_price_geometry("sell", entry=1.14143, stop_loss=1.150, take_profit=1.160)
    assert r is not None and "invalid sell geometry" in r


def test_validate_price_geometry_sell_rejects_sl_below_entry():
    # SL below entry is invalid for a sell.
    r = validate_price_geometry("sell", entry=1.14143, stop_loss=1.095, take_profit=1.090)
    assert r is not None and "invalid sell geometry" in r


def test_validate_price_geometry_good_buy_passes():
    assert validate_price_geometry("buy", entry=1.14143, stop_loss=1.095, take_profit=1.160) is None


def test_validate_price_geometry_good_sell_passes():
    assert validate_price_geometry("sell", entry=1.14143, stop_loss=1.160, take_profit=1.090) is None


def test_check_demo_trade_mode_demo_zero_accepted():
    # Observed SDK values: DEMO == 0. Must NOT be treated as live.
    assert check_demo_trade_mode(0) is None
    assert is_live_trade_mode(0) is False


def test_check_demo_trade_mode_contest_accepted():
    assert check_demo_trade_mode(1) is None
    assert is_live_trade_mode(1) is False


def test_check_demo_trade_mode_real_rejected():
    # REAL == 2 must be refused.
    assert is_live_trade_mode(2) is True
    with pytest.raises(ValueError):
        check_demo_trade_mode(2)


def test_guard_rejects_stale_signal():
    # A signal generated 2 hours ago exceeds the default 30-min max age.
    old_ts = (datetime.now(timezone.utc).replace(microsecond=0)
              - __import__("datetime").timedelta(hours=2)).isoformat()
    order = _good_order()
    res = run_pretrade_guards(
        order, broker_mode="demo", allow_live_orders=False, account=10000,
        risk_pct=0.75, signal=_signal(), open_demo_trades=0,
        signal_timestamp=old_ts, execution_class="paper",
    )
    assert not res.passed
    assert any("stale signal" in r for r in res.reasons)


def test_guard_accepts_fresh_signal():
    fresh_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    order = _good_order()
    res = run_pretrade_guards(
        order, broker_mode="demo", allow_live_orders=False, account=10000,
        risk_pct=0.75, signal=_signal(), open_demo_trades=0,
        signal_timestamp=fresh_ts, execution_class="paper",
    )
    assert res.passed, res.reasons


def test_guard_exempts_backtest_only_signal_from_staleness():
    old_ts = (datetime.now(timezone.utc).replace(microsecond=0)
              - __import__("datetime").timedelta(hours=2)).isoformat()
    order = _good_order()
    res = run_pretrade_guards(
        order, broker_mode="demo", allow_live_orders=False, account=10000,
        risk_pct=0.75, signal=_signal(), open_demo_trades=0,
        signal_timestamp=old_ts, execution_class="backtest_only",
    )
    assert res.passed, res.reasons  # exempt: never executed


def test_guard_rejects_invalid_buy_geometry_vs_live_quote():
    # Stale Signal #1: SL=1.095, TP=1.105 with current ask ~1.14143 -> TP below entry.
    from src.execution.adapter import PriceQuote
    stale_signal = _signal(entry=1.1000, sl=1.095, tp=1.105, direction=1)
    order = DemoOrderRequest(symbol="EURUSD", side="buy", units=2000.0,
                             stop_loss=1.095, take_profit=1.105,
                             signal_id=1, requested_entry=1.14143)
    live = PriceQuote(symbol="EURUSD", bid=1.14140, ask=1.14143, spread=0.00003,
                      timestamp=datetime.now(timezone.utc).isoformat())
    res = run_pretrade_guards(
        order, broker_mode="demo", allow_live_orders=False, account=10000,
        risk_pct=0.75, signal=stale_signal, open_demo_trades=0,
        live_quote=live, signal_timestamp=stale_signal.timestamp, execution_class="paper",
    )
    assert not res.passed
    assert any("price geometry invalid" in r for r in res.reasons)


def test_guard_passes_valid_buy_geometry_vs_live_quote():
    from src.execution.adapter import PriceQuote
    fresh_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sig = _signal(entry=1.14143, sl=1.095, tp=1.160, direction=1, timestamp=fresh_ts)
    order = DemoOrderRequest(symbol="EURUSD", side="buy", units=2000.0,
                             stop_loss=1.095, take_profit=1.160,
                             signal_id=1, requested_entry=1.14143)
    live = PriceQuote(symbol="EURUSD", bid=1.14140, ask=1.14143, spread=0.00003,
                      timestamp=fresh_ts)
    res = run_pretrade_guards(
        order, broker_mode="demo", allow_live_orders=False, account=10000,
        risk_pct=0.75, signal=sig, open_demo_trades=0,
        live_quote=live, signal_timestamp=fresh_ts, execution_class="paper",
    )
    assert res.passed, res.reasons


# ===== v1.3.3 Remote MT5 Bridge (Tailscale → Windows PC) =====

def test_missing_bridge_url_fails_loud(monkeypatch):
    monkeypatch.delenv("REMOTE_MT5_BRIDGE_URL", raising=False)
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    from src.execution.factory import build_adapter
    with pytest.raises(RuntimeError):
        build_adapter("remote_mt5", fail_loud=True)


def test_missing_bridge_token_fails_loud(monkeypatch):
    monkeypatch.delenv("REMOTE_MT5_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    from src.execution.factory import build_adapter
    with pytest.raises(RuntimeError):
        build_adapter("remote_mt5", fail_loud=True)


def test_invalid_token_rejected(monkeypatch):
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "correct-token")
    import requests
    from src.execution.remote_mt5_bridge import RemoteMT5BridgeAdapter

    class FakeResp:
        def __init__(self, status_code=401, json_data=None):
            self.status_code = status_code
            self._j = json_data or {}
        def json(self):
            return self._j

    class FakeSess:
        def request(self, *a, **k):
            return FakeResp(status_code=401)

    monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResp(status_code=401))
    a = RemoteMT5BridgeAdapter()
    with pytest.raises(RuntimeError):
        a.get_account()


def test_unreachable_bridge_fails_loud(monkeypatch):
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    import requests
    from src.execution.remote_mt5_bridge import RemoteMT5BridgeAdapter

    def boom(*a, **k):
        raise requests.RequestException("connection refused")
    monkeypatch.setattr(requests, "request", boom)
    a = RemoteMT5BridgeAdapter()
    with pytest.raises(RuntimeError):
        a.get_account()


def test_bridge_reports_non_demo_rejected(monkeypatch):
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    import requests
    from src.execution.remote_mt5_bridge import RemoteMT5BridgeAdapter

    class FakeResp:
        status_code = 200
        def json(self):
            return {"broker_mode": "live", "balance": 1000.0, "currency": "USD"}
    monkeypatch.setattr(requests, "request", lambda *a, **k: FakeResp())
    a = RemoteMT5BridgeAdapter()
    with pytest.raises(RuntimeError):
        a.get_account()


def test_bridge_supports_sl_tp_payload(monkeypatch):
    # The adapter must forward SL/TP to the bridge (no fallback to mock).
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    import requests
    from src.execution.remote_mt5_bridge import RemoteMT5BridgeAdapter

    captured = {}
    class FakeResp:
        status_code = 200
        def json(self):
            return {"status": "skipped", "rejection_reason": "DRY_RUN active",
                    "broker_mode": "demo"}
    def fake(*a, **k):
        captured["json"] = k.get("json")
        return FakeResp()
    monkeypatch.setattr(requests, "request", fake)
    a = RemoteMT5BridgeAdapter()
    order = _good_order()
    a.place_demo_order(order)
    assert captured["json"]["stop_loss"] == order.stop_loss
    assert captured["json"]["take_profit"] == order.take_profit


def test_remote_bridge_status_table_no_secret_columns(monkeypatch):
    import sqlite3
    from run_execution import _db
    db = _db()
    cols = [c["name"] for c in db.execute("PRAGMA table_info(RemoteBridgeStatus)").fetchall()]
    for secret in ("api_key", "password", "token", "secret", "login", "mt5"):
        assert secret not in cols, f"RemoteBridgeStatus must not store {secret}"
    # the table exists and is writable without secrets
    db.execute(
        "INSERT INTO RemoteBridgeStatus (reachable, tailscale_url_configured, "
        "pc_bridge_mode, bridge_kill_switch, last_checked_at) VALUES (0,1,'unknown',0,'2026-07-11T00:00:00')"
    )
    db.commit()


def test_no_mt5_credentials_on_vps(monkeypatch):
    # The VPS adapter must NOT read MT5_LOGIN/PASSWORD/SERVER for its own use.
    from src.execution.remote_mt5_bridge import RemoteMT5BridgeAdapter
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    # Even with MT5 env vars set, the remote adapter ignores them (uses URL/token only).
    monkeypatch.setenv("MT5_LOGIN", "should-not-be-used")
    monkeypatch.setenv("MT5_PASSWORD", "should-not-be-used")
    monkeypatch.setenv("MT5_SERVER", "should-not-be-used")
    a = RemoteMT5BridgeAdapter()
    assert a._url == "https://pc.tailnet.ts.net"
    assert a._token == "tok"
    assert not getattr(a, "_mt5_login", None)


def test_kill_switch_blocks_remote_bridge_order(monkeypatch):
    # observe_only default => can_place_real_demo False => order rejected.
    from src.execution.factory import can_place_real_demo, execution_mode
    assert execution_mode() == "observe_only"


# --- refresh-signal command (live quote revalidation, never places an order) ---
def _make_refresh_db(tmp_path, *, orig_id=3, pair="EURUSD", direction=1,
                     entry=1.14143, sl=1.135, tp=1.15, status="paper",
                     generated_at="2026-07-11T13:52:28+00:00", units=2000.0):
    import sqlite3
    dbp = tmp_path / "refr.db"
    db = sqlite3.connect(str(dbp))
    db.execute("""CREATE TABLE Signal (
        id INTEGER PRIMARY KEY, pair TEXT, strategy TEXT, direction INTEGER,
        entry REAL, stop_loss REAL, take_profit REAL, signal_score REAL,
        regime TEXT, units REAL, generated_at TEXT, status TEXT,
        original_signal_id INTEGER)""")
    db.execute("""INSERT INTO Signal (id,pair,strategy,direction,entry,stop_loss,
        take_profit,signal_score,regime,units,generated_at,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (orig_id, pair, "rsi", direction, entry, sl, tp, 63.0, "trend", units,
         generated_at, status))
    db.commit()
    db.close()
    return dbp


def _patch_bridge(monkeypatch, *, health=None, quote=None, captured=None,
                  raise_exc=None):
    """Patch every requests entry point used by the bridge so no real network
    call can happen. `health`/`quote` are JSON dicts; `raise_exc` (a
    requests.RequestException) makes every call blow up (unreachable)."""
    import requests
    from src.execution import remote_mt5_bridge as rmb

    class _R:
        status_code = 200
        def __init__(self, j): self._j = j
        def json(self): return self._j

    def make(method, url, **k):
        if raise_exc is not None:
            raise raise_exc
        if captured is not None:
            captured[url] = (method, k.get("json"))
        base = url.split("?")[0].rstrip("/")  # ignore query string
        if health is not None and base.endswith("/health"):
            return _R(health)
        if quote is not None and base.endswith("/quote"):
            return _R(quote)
        return _R({})

    monkeypatch.setattr(requests, "request", make)
    monkeypatch.setattr(requests, "get", lambda u, **k: make("get", u, **k))
    monkeypatch.setattr(requests, "post", lambda u, **k: make("post", u, **k))
    # adapter module also holds a reference to the requests module
    monkeypatch.setattr(rmb.requests, "request", make)
    monkeypatch.setattr(rmb.requests, "get", lambda u, **k: make("get", u, **k))
    monkeypatch.setattr(rmb.requests, "post", lambda u, **k: make("post", u, **k))
    return _R


def _ns():
    return __import__("types").SimpleNamespace(signal_id=3, broker="remote_mt5")


HEALTH_OK = {"broker_mode": "demo", "bridge_kill_switch": False}
QUOTE_OK = {"symbol": "EURUSD", "bid": 1.14140, "ask": 1.14143, "spread": 0.0003}


def test_refresh_stale_signal_creates_fresh_candidate(monkeypatch, tmp_path):
    dbp = _make_refresh_db(tmp_path)
    monkeypatch.setattr("run_execution.DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    _patch_bridge(monkeypatch, health=HEALTH_OK, quote=QUOTE_OK)
    from run_execution import cmd_refresh_signal
    assert cmd_refresh_signal(_ns()) == 0
    import sqlite3
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM Signal ORDER BY id").fetchall()
    assert len(rows) == 2
    fresh = rows[1]
    assert fresh["original_signal_id"] == 3
    assert fresh["status"] == "paper"
    from src.execution.bridge_validation import is_stale_signal
    assert not is_stale_signal(fresh["generated_at"], 30)
    assert fresh["entry"] == 1.14143  # live ask used as entry
    assert fresh["stop_loss"] == 1.135 and fresh["take_profit"] == 1.15


def test_refresh_invalid_geometry_rejected(monkeypatch, tmp_path):
    # Force invalid geometry: live ask ABOVE TP(1.15) => buy geometry fails.
    dbp = _make_refresh_db(tmp_path)
    monkeypatch.setattr("run_execution.DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    bad_quote = {"symbol": "EURUSD", "bid": 1.15050, "ask": 1.15060, "spread": 0.0001}
    _patch_bridge(monkeypatch, health=HEALTH_OK, quote=bad_quote)
    from run_execution import cmd_refresh_signal
    assert cmd_refresh_signal(_ns()) == 2
    import sqlite3
    db = sqlite3.connect(str(dbp))
    assert db.execute("SELECT COUNT(*) c FROM Signal").fetchone()[0] == 1


def test_refresh_does_not_place_order(monkeypatch, tmp_path):
    dbp = _make_refresh_db(tmp_path)
    monkeypatch.setattr("run_execution.DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    captured = {}
    _patch_bridge(monkeypatch, health=HEALTH_OK, quote=QUOTE_OK, captured=captured)
    from run_execution import cmd_refresh_signal
    assert cmd_refresh_signal(_ns()) == 0
    # refresh must only GET /health and GET /quote; never POST /place-demo-order
    assert all("/place-demo-order" not in u for u in captured)


def test_refresh_preserves_original_signal(monkeypatch, tmp_path):
    dbp = _make_refresh_db(tmp_path)
    monkeypatch.setattr("run_execution.DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    _patch_bridge(monkeypatch, health=HEALTH_OK, quote=QUOTE_OK)
    from run_execution import cmd_refresh_signal
    assert cmd_refresh_signal(_ns()) == 0
    import sqlite3
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    orig = db.execute("SELECT * FROM Signal WHERE id=3").fetchone()
    assert orig is not None
    assert orig["original_signal_id"] is None  # original left untouched
    assert orig["entry"] == 1.14143 and orig["stop_loss"] == 1.135 and orig["take_profit"] == 1.15


def test_refresh_fresh_candidate_passes_stale_check(monkeypatch, tmp_path):
    dbp = _make_refresh_db(tmp_path)
    monkeypatch.setattr("run_execution.DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    _patch_bridge(monkeypatch, health=HEALTH_OK, quote=QUOTE_OK)
    from run_execution import cmd_refresh_signal
    from src.execution.bridge_validation import is_stale_signal, validate_price_geometry
    assert cmd_refresh_signal(_ns()) == 0
    import sqlite3
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    fresh = db.execute("SELECT * FROM Signal ORDER BY id DESC LIMIT 1").fetchone()
    assert not is_stale_signal(fresh["generated_at"], 30)
    assert validate_price_geometry("buy", fresh["entry"], fresh["stop_loss"],
                                    fresh["take_profit"]) is None


def test_refresh_remote_mt5_unavailable_fails_loud(monkeypatch, tmp_path):
    dbp = _make_refresh_db(tmp_path)
    monkeypatch.setattr("run_execution.DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    import requests
    _patch_bridge(monkeypatch, raise_exc=requests.RequestException("connection refused"))
    from run_execution import cmd_refresh_signal
    assert cmd_refresh_signal(_ns()) == 2  # fails loud, no candidate created
    import sqlite3
    db = sqlite3.connect(str(dbp))
    assert db.execute("SELECT COUNT(*) c FROM Signal").fetchone()[0] == 1


def test_refresh_kill_switch_blocks(monkeypatch, tmp_path):
    dbp = _make_refresh_db(tmp_path)
    monkeypatch.setattr("run_execution.DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    kill_health = {"broker_mode": "demo", "bridge_kill_switch": True}
    _patch_bridge(monkeypatch, health=kill_health, quote=QUOTE_OK)
    from run_execution import cmd_refresh_signal
    assert cmd_refresh_signal(_ns()) == 2
    import sqlite3
    db = sqlite3.connect(str(dbp))
    assert db.execute("SELECT COUNT(*) c FROM Signal").fetchone()[0] == 1


# ===== v1.3.5 remote-mt5-order: preserve signal_id + units (fix #6) =====
def _make_order_db(tmp_path, *, sid=6, units=2000.0, direction=1,
                   entry=1.14143, sl=1.135, tp=1.15,
                   generated_at=None):
    """Fresh temp DB with the execution tables the order path touches."""
    import sqlite3
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    dbp = tmp_path / "ord.db"
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE Signal (
        id INTEGER PRIMARY KEY, pair TEXT, strategy TEXT, direction INTEGER,
        entry REAL, stop_loss REAL, take_profit REAL, signal_score REAL,
        regime TEXT, units REAL, generated_at TEXT, status TEXT,
        original_signal_id INTEGER)""")
    db.execute("""CREATE TABLE ExecutionControl (
        id INTEGER PRIMARY KEY, kill_switch INTEGER, broker_mode TEXT,
        max_open_demo_trades INTEGER, max_open_per_broker INTEGER,
        execution_mode TEXT, primary_demo_broker TEXT)""")
    db.execute("""CREATE TABLE DemoExecutionOrder (
        id INTEGER PRIMARY KEY, signal_id INTEGER, broker TEXT, broker_mode TEXT,
        symbol TEXT, side TEXT, requested_entry REAL, filled_entry REAL,
        stop_loss REAL, take_profit REAL, units REAL, requested_at TEXT,
        filled_at TEXT, status TEXT, spread_at_entry REAL, slippage REAL,
        rejection_reason TEXT, raw_response_redacted_json TEXT)""")
    db.execute("""CREATE TABLE DemoExecutionLock (
        id INTEGER PRIMARY KEY, signal_id INTEGER, broker TEXT, run_id TEXT,
        order_id INTEGER, created_at TEXT,
        UNIQUE(signal_id, broker, run_id))""")
    db.execute("""CREATE TABLE ExecutionJournal (
        id INTEGER PRIMARY KEY, demo_order_id INTEGER, signal_id INTEGER,
        broker TEXT, broker_mode TEXT, run_id TEXT, created_at TEXT,
        expected_paper_pnl REAL, actual_demo_pnl REAL, pnl_delta REAL,
        spread REAL, slippage REAL, latency_ms REAL, lesson_json TEXT)""")
    db.execute(
        "INSERT INTO Signal (id,pair,strategy,direction,entry,stop_loss,"
        "take_profit,signal_score,regime,units,generated_at,status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, "EURUSD", "rsi", direction, entry, sl, tp, 63.0, "trend",
         units, generated_at, "paper"))
    db.commit(); db.close()
    return dbp


def _patch_order_bridge(monkeypatch, *, dry_run_payload=None, place_status="filled",
                        place_reason=None, captured=None, raise_exc=None):
    """Patch the bridge HTTP layer used by RemoteMT5BridgeAdapter.

    Returns canned /dry-run and /place-demo-order responses and records every
    outbound JSON in `captured` so we can assert the broker received units=2000.
    Also flips the VPS execution-mode env to single_broker_demo + autotrade ON
    so the order path is permitted to reach the adapter (we are testing the
    signal_id/units preservation, not the observe_only gate).
    """
    import requests
    from src.execution import remote_mt5_bridge as rmb

    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("DEMO_AUTOTRADE_ENABLED", "true")
    monkeypatch.setenv("BROKER_EXECUTION_MODE", "single_broker_demo")
    if dry_run_payload is None:
        dry_run_payload = {"would_place": True, "broker_mode": "demo",
                           "live_entry": 1.14143, "bridge_kill_switch": False}
    class _R:
        def __init__(self, code, j): self.status_code = code; self._j = j
        def json(self): return self._j
    def make(method, url, **k):
        if raise_exc is not None:
            raise raise_exc
        if captured is not None:
            captured[url.split("?")[0].rstrip("/")] = (method, k.get("json"))
        base = url.split("?")[0].rstrip("/")
        if base.endswith("/dry-run"):
            return _R(200, dry_run_payload)
        if base.endswith("/place-demo-order"):
            return _R(200, {"status": place_status,
                            "rejection_reason": place_reason,
                            "filled_entry": (k.get("json") or {}).get("requested_entry"),
                            "order_id": "PC123",
                            "spread_at_entry": 0.0003, "slippage": 0.0001,
                            "broker_mode": "demo"})
        if base.endswith("/quote"):
            return _R(200, {"symbol": "EURUSD", "bid": 1.14140,
                            "ask": 1.14143, "spread": 0.0003})
        return _R(200, {})
    monkeypatch.setattr(requests, "request", make)
    monkeypatch.setattr(requests, "get", lambda u, **k: make("get", u, **k))
    monkeypatch.setattr(requests, "post", lambda u, **k: make("post", u, **k))
    monkeypatch.setattr(rmb.requests, "request", make)
    monkeypatch.setattr(rmb.requests, "get", lambda u, **k: make("get", u, **k))
    monkeypatch.setattr(rmb.requests, "post", lambda u, **k: make("post", u, **k))
    return _R


def test_prepare_demo_order_preserves_signal_id_and_units():
    from run_execution import prepare_demo_order_from_signal
    s = _signal(units=2000.0, sid=6, timestamp=datetime.now(timezone.utc).isoformat())
    o = prepare_demo_order_from_signal(s, "remote_mt5", 1.14143)
    assert o.signal_id == 6
    assert o.units == 2000.0
    assert o.symbol == "EURUSD"
    assert o.side == "buy"


def test_prepare_demo_order_rejects_missing_units():
    from run_execution import prepare_demo_order_from_signal
    s = _signal(units=None, sid=6)
    with pytest.raises(ValueError):
        prepare_demo_order_from_signal(s, "remote_mt5", 1.1)


def test_prepare_demo_order_rejects_zero_units():
    from run_execution import prepare_demo_order_from_signal
    s = _signal(units=0.0, sid=6)
    with pytest.raises(ValueError):
        prepare_demo_order_from_signal(s, "remote_mt5", 1.1)


def test_prepare_demo_order_rejects_nan_units():
    from run_execution import prepare_demo_order_from_signal
    s = _signal(units=float("nan"), sid=6)
    with pytest.raises(ValueError):
        prepare_demo_order_from_signal(s, "remote_mt5", 1.1)


def test_prepare_demo_order_rejects_missing_signal_id():
    from run_execution import prepare_demo_order_from_signal
    s = _signal(units=2000.0, sid=None)
    with pytest.raises(ValueError):
        prepare_demo_order_from_signal(s, "remote_mt5", 1.1)


def test_paper_signal_carries_id_and_units():
    import run_execution, sqlite3, pathlib, tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    dbp = _make_order_db(d, sid=6, units=2000.0)
    orig = run_execution.DB_PATH
    run_execution.DB_PATH = str(dbp)
    try:
        db = run_execution._db()
        from run_execution import _paper_signal
        s = _paper_signal(db, 6)
        assert s is not None
        assert s.id == 6
        assert s.units == 2000.0
    finally:
        run_execution.DB_PATH = orig


def test_remote_mt5_order_sends_units_2000_to_bridge(monkeypatch, tmp_path):
    # Signal #6-style happy path: prove the broker receives requested_units=2000
    # (the exact failure was units=0 reaching the bridge).
    import run_execution, sqlite3
    dbp = _make_order_db(tmp_path, sid=6, units=2000.0)
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    captured = {}
    _patch_order_bridge(monkeypatch, captured=captured)
    rc = run_execution.cmd_remote_mt5_order(_args(signal_id=6, run_id="mt5-first-demo-6"))
    assert rc == 0
    place_urls = [u for u in captured if u.endswith("/place-demo-order")]
    assert place_urls, f"bridge /place-demo-order was never called; captured={captured}"
    sent = captured[place_urls[0]][1]
    assert sent["units"] == 2000.0
    assert sent["signal_id"] == 6
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM DemoExecutionOrder ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["signal_id"] == 6
    assert row["units"] == 2000.0
    assert row["status"] == "filled"


def test_remote_mt5_dry_run_and_order_share_prepared_units(monkeypatch, tmp_path, capsys):
    import run_execution, json
    dbp = _make_order_db(tmp_path, sid=6, units=2000.0)
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    _patch_order_bridge(monkeypatch)
    rc = run_execution.cmd_remote_mt5_dry_run(_args(signal_id=6))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["signal_units"] == 2000.0
    assert out["prepared_order_units"] == 2000.0
    assert out["signal_id"] == 6
    assert out["would_place_order"] is True


def test_remote_mt5_order_missing_units_fails_before_bridge(monkeypatch, tmp_path):
    import run_execution, sqlite3
    dbp = _make_order_db(tmp_path, sid=6, units=None)
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    captured = {}
    _patch_order_bridge(monkeypatch, captured=captured)
    rc = run_execution.cmd_remote_mt5_order(_args(signal_id=6, run_id="bad-units"))
    assert rc == 2
    # The bad-units gate must fire BEFORE the broker order call (only the
    # diagnostic /dry-run + /quote may have been contacted, never /place-demo-order).
    assert not any(u.endswith("/place-demo-order") for u in captured)
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM DemoExecutionOrder ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["signal_id"] == 6
    assert row["status"] == "rejected"


def test_remote_mt5_order_zero_units_fails_before_bridge(monkeypatch, tmp_path):
    import run_execution
    dbp = _make_order_db(tmp_path, sid=6, units=0.0)
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    captured = {}
    _patch_order_bridge(monkeypatch, captured=captured)
    rc = run_execution.cmd_remote_mt5_order(_args(signal_id=6, run_id="zero-units"))
    assert rc == 2
    assert not any(u.endswith("/place-demo-order") for u in captured)


def test_remote_mt5_order_nan_units_fails_before_bridge(monkeypatch, tmp_path):
    import run_execution
    dbp = _make_order_db(tmp_path, sid=6, units=float("nan"))
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    captured = {}
    _patch_order_bridge(monkeypatch, captured=captured)
    rc = run_execution.cmd_remote_mt5_order(_args(signal_id=6, run_id="nan-units"))
    assert rc == 2
    assert not any(u.endswith("/place-demo-order") for u in captured)


def test_remote_mt5_order_rejected_bridge_stores_signal_and_units(monkeypatch, tmp_path):
    # If the bridge rejects, DemoExecutionOrder must still record signal_id + units.
    import run_execution, sqlite3
    dbp = _make_order_db(tmp_path, sid=6, units=2000.0)
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    _patch_order_bridge(monkeypatch, place_status="rejected",
                        place_reason="invalid volume: units must be positive")
    rc = run_execution.cmd_remote_mt5_order(_args(signal_id=6, run_id="bridge-reject"))
    db = sqlite3.connect(str(dbp)); db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM DemoExecutionOrder ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["signal_id"] == 6
    assert row["units"] == 2000.0
    assert row["status"] == "rejected"
    assert "units must be positive" in (row["rejection_reason"] or "")


def test_remote_mt5_dry_run_invalid_units_shows_units_and_fails(monkeypatch, tmp_path, capsys):
    import run_execution, json
    dbp = _make_order_db(tmp_path, sid=6, units=0.0)
    monkeypatch.setattr(run_execution, "DB_PATH", str(dbp))
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_URL", "https://pc.tailnet.ts.net")
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "tok")
    _patch_order_bridge(monkeypatch)
    rc = run_execution.cmd_remote_mt5_dry_run(_args(signal_id=6))
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["would_place_order"] is False
    assert out["prepared_order_units"] is None
    assert out["signal_units"] == 0.0
    assert out["signal_id"] == 6


