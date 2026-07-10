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
