"""Tests for the PC bridge volume normalization + order_check/order_send path.

These run on the VPS (no MetaTrader5 / FastAPI needed) because all broker
interaction is injected via a fake `mt5` module. They prove:
  * units=2000 -> 0.2 lots (Signal #5 case)
  * units=0.2 stays 0.2 lots
  * tiny/zero units are clamped/rejected safely
  * order_check failure prevents order_send
  * order_send rejection returns debug-safe volume fields
  * live (non-demo) broker mode is refused outright
"""
from __future__ import annotations

import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge_validation import normalize_volume, VolumeInfo, execute_demo_order


# ---------- fake MT5 module ----------
class _Symbol:
    def __init__(self, vmin=0.01, vstep=0.01, vmax=100.0):
        self.volume_min = vmin
        self.volume_step = vstep
        self.volume_max = vmax


class _FakeResult:
    def __init__(self, retcode, comment="", order="", price=0.0):
        self.retcode = retcode
        self.comment = comment
        self.order = order
        self.price = price


class _FakeMT5:
    TRADE_RETCODE_DONE = 0
    TRADE_ACTION_DEAL = "deal"
    ORDER_TYPE_BUY = "buy"
    ORDER_TYPE_SELL = "sell"
    ORDER_TIME_GTC = "gtc"
    ORDER_FILLING_IOC = "ioc"

    def __init__(self, *, fail_order_check=False, fail_order_send=False,
                 check_none=False, symbol=None):
        self._fail_order_check = fail_order_check
        self._fail_order_send = fail_order_send
        self._check_none = check_none
        self._symbol = symbol or _Symbol()
        self.order_send_called = False
        self.last_request = None

    def symbol_info(self, _sym):
        return self._symbol

    def order_check(self, request):
        if self._check_none:
            return None
        if self._fail_order_check:
            return _FakeResult(10014, "invalid volume")
        return _FakeResult(self.TRADE_RETCODE_DONE)

    def order_send(self, request):
        self.order_send_called = True
        self.last_request = request
        if self._fail_order_send:
            return _FakeResult(10014, "invalid volume")
        return _FakeResult(self.TRADE_RETCODE_DONE, order="12345", price=request.get("price", 0.0))


def _info(min=0.01, step=0.01, max=100.0):
    return VolumeInfo(min, step, max)


# ---------- normalize_volume ----------
def test_units_2000_normalizes_to_0_2_lots():
    # Signal #5: units=2000 -> 2000/10000 = 0.2 lots (Aether's unit scale).
    out = normalize_volume(2000, _info(min=0.01, step=0.01, max=100.0))
    assert out["requested_units"] == 2000.0
    assert round(out["calculated_lots"], 4) == 0.2
    assert round(out["normalized_lots"], 4) == 0.2
    assert out["valid"] is True


def test_units_0_2_stays_0_2_lots():
    out = normalize_volume(0.2, _info(min=0.01, step=0.01, max=100.0))
    assert round(out["calculated_lots"], 4) == 0.2
    assert round(out["normalized_lots"], 4) == 0.2
    assert out["valid"] is True


def test_tiny_units_rejected():
    # 0.005 lots with min 0.01 / step 0.01 -> cannot satisfy min -> invalid.
    out = normalize_volume(0.005, _info(min=0.01, step=0.01, max=100.0))
    assert out["normalized_lots"] == 0.0
    assert out["valid"] is False
    assert out["reason"] is not None


def test_zero_units_rejected():
    out = normalize_volume(0, _info(min=0.01, step=0.01, max=100.0))
    assert out["valid"] is False
    assert out["normalized_lots"] == 0.0


def test_negative_units_rejected():
    out = normalize_volume(-50, _info(min=0.01, step=0.01, max=100.0))
    assert out["valid"] is False


def test_volume_snaps_to_step():
    # 0.2 lots, step 0.1 -> snaps to 0.2 (already multiple). step 0.05 -> 0.2.
    out = normalize_volume(0.2, _info(min=0.01, step=0.05, max=100.0))
    assert round(out["normalized_lots"], 4) == 0.2


# ---------- execute_demo_order ----------
def _base_request():
    return {
        "action": _FakeMT5.TRADE_ACTION_DEAL,
        "symbol": "EURUSD",
        "volume": 0.2,
        "type": _FakeMT5.ORDER_TYPE_BUY,
        "price": 1.14143,
        "sl": 1.135,
        "tp": 1.15,
        "requested_units": 2000.0,
        "calculated_lots": 0.2,
        "spread_at_entry": 0.0003,
    }


def test_order_check_failure_prevents_order_send():
    mt5 = _FakeMT5(fail_order_check=True)
    res = execute_demo_order(mt5, _base_request(), "EURUSD", broker_mode="demo")
    assert res["status"] == "rejected"
    assert res["order_check_retcode"] == 10014
    assert mt5.order_send_called is False
    # debug-safe volume fields present, no secrets
    assert res["requested_units"] == 2000.0
    assert res["normalized_lots"] == 0.2
    assert res["volume_min"] == 0.01
    assert "token" not in str(res).lower()


def test_order_check_none_rejected():
    mt5 = _FakeMT5(check_none=True)
    res = execute_demo_order(mt5, _base_request(), "EURUSD", broker_mode="demo")
    assert res["status"] == "rejected"
    assert res["request_volume"] == 0.2
    assert mt5.order_send_called is False


def test_order_send_rejection_returns_debug_fields():
    mt5 = _FakeMT5(fail_order_send=True)
    res = execute_demo_order(mt5, _base_request(), "EURUSD", broker_mode="demo")
    assert res["status"] == "rejected"
    assert res["mt5_retcode"] == 10014
    assert res["request_symbol"] == "EURUSD"
    assert res["request_side"] == "buy"
    assert res["normalized_lots"] == 0.2
    assert res["volume_min"] == 0.01
    assert res["broker_mode"] == "demo"


def test_successful_fill_returns_volume():
    mt5 = _FakeMT5()
    res = execute_demo_order(mt5, _base_request(), "EURUSD", broker_mode="demo")
    assert res["status"] == "filled"
    assert res["order_id"] == "12345"
    assert res["volume"] == 0.2
    assert mt5.order_send_called is True


def test_no_live_mode_allowed():
    mt5 = _FakeMT5()
    res = execute_demo_order(mt5, _base_request(), "EURUSD", broker_mode="real")
    assert res["status"] == "refused"
    assert "live" in res["rejection_reason"].lower()
    assert mt5.order_send_called is False
