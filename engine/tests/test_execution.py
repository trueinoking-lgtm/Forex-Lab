"""Tests for the demo execution bridge (engine/src/execution)."""
from __future__ import annotations

import os
import sys
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
)


def _signal(entry=1.1000, sl=1.0950, tp=1.1050, direction=1, units=2000.0, sid=1):
    return PaperSignal(
        pair="EURUSD", strategy="rsi", direction=direction, entry=entry,
        stop_loss=sl, take_profit=tp, signal_score=60.0, regime="trend",
        timestamp="2026-07-10T00:00:00", units=units,
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
    for k in ("DERIV_MT5_LOGIN", "DERIV_MT5_PASSWORD", "DERIV_MT5_SERVER",
              "OANDA_PRACTICE_API_KEY", "OANDA_PRACTICE_ACCOUNT"):
        os.environ.pop(k, None)
    av = available_adapters()
    assert av["deriv_mt5"] is False
    assert av["oanda_practice"] is False
    # fail_loud=True raises when requested without creds
    with pytest.raises(RuntimeError):
        build_adapter("deriv_mt5", fail_loud=True)
    with pytest.raises(RuntimeError):
        build_adapter("oanda_practice", fail_loud=True)
    # fail_loud=False falls back to mock
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
