"""Unit tests for bridge_validation.execute_demo_order filling-mode logic.

These run WITHOUT the MetaTrader5 SDK by injecting a fake `mt5` object whose
order_check / order_send behave like the LIVE broker:

  * The symbol uses Market Execution (trade_exemode == 2) with FOK only
    (filling_mode == 1).
  * For a TRADE_ACTION_DEAL market order under Market Execution the terminal
    fills at market, so we send price=0 and the FOK filling policy. RETURN is
    NOT valid here (MQL5: ORDER_FILLING_RETURN disallowed for
    SYMBOL_TRADE_EXECUTION_MARKET).

The test asserts:
  * Candidates are derived ONLY from the symbol's filling_mode flags (FOK/IOC),
    never RETURN.
  * For Market Execution the sanitized request sent to MT5 has price=0 and only
    valid MqlTradeRequest keys (no debug leakage).
  * order_send fall-through works on 10018/10030; exactly one position opens.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from bridge_validation import (
    execute_demo_order,
    _order_check_passed,
    _order_send_succeeded,
    UNITS_PER_LOT,
    is_stale_signal,
)
from server import OrderReq


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def _valid_order(**overrides):
    values = {
        "symbol": "EURUSD", "side": "buy", "units": 2000,
        "stop_loss": 1.1, "take_profit": 1.2,
    }
    values.update(overrides)
    return values


def test_unknown_signal_age_is_stale_for_executable_class():
    assert is_stale_signal(None, 30, "paper", NOW) is True
    future = (NOW + timedelta(minutes=10)).isoformat()
    assert is_stale_signal(future, 30, "paper", NOW) is True
    recent = (NOW - timedelta(minutes=1)).isoformat()
    assert is_stale_signal(recent, 30, "paper", NOW) is False


@pytest.mark.parametrize("override", [
    {"side": "hold"},
    {"units": float("nan")},
    {"symbol": "UNKNOWN"},
])
def test_order_request_rejects_invalid_boundary_fields(override):
    with pytest.raises(ValidationError):
        OrderReq(**_valid_order(**override))


class _FakeCheck:
    def __init__(self, retcode=0, comment=""):
        self.retcode = retcode
        self.comment = comment


class _FakeResult:
    def __init__(self, retcode=10009, order="77", deal="78", position="79",
                 price=1.14143, volume=0.02, comment="request done"):
        self.retcode = retcode
        self.order = order
        self.deal = deal
        self.position = position
        self.price = price
        self.volume = volume
        self.comment = comment


class FakeMt5:
    """Market Execution broker: accepts FOK (price=0); rejects IOC (10030)."""

    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_ACTION_DEAL = 1
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_MARKET_CLOSED = 10018
    TRADE_RETCODE_UNSUPPORTED_FILLING_MODE = 10030

    def __init__(self):
        self.sends = []          # type_filling values passed to order_send
        self.check_requests = []  # sanitized requests seen by order_check
        self.send_requests = []   # sanitized requests seen by order_send
        self.opens = 0
        self._last_error = {"code": -1, "description": ""}

    def last_error(self):
        return type("E", (), self._last_error)()

    def order_check(self, request):
        self.check_requests.append(dict(request))
        if request.get("type_filling") == self.ORDER_FILLING_IOC:
            return _FakeCheck(retcode=self.TRADE_RETCODE_UNSUPPORTED_FILLING_MODE,
                              comment="unsupported filling mode")
        return _FakeCheck(retcode=0, comment="done")

    def order_send(self, request):
        self.send_requests.append(dict(request))
        filling = request.get("type_filling")
        self.sends.append(filling)
        if filling == self.ORDER_FILLING_IOC:
            self._last_error = {"code": self.TRADE_RETCODE_UNSUPPORTED_FILLING_MODE,
                                "description": "unsupported filling mode"}
            return _FakeResult(retcode=self.TRADE_RETCODE_UNSUPPORTED_FILLING_MODE)
        # FOK (price=0) accepted -> a single position opens.
        self.opens += 1
        return _FakeResult(retcode=self.TRADE_RETCODE_DONE)


def _symbol_info(filling_mode=1, trade_exemode=2):
    class S:
        pass
    s = S()
    s.volume_min = 0.01
    s.volume_step = 0.01
    s.volume_max = 500.0
    s.filling_mode = filling_mode
    s.trade_exemode = trade_exemode
    return s


def _make_request(units=2000, side="buy", symbol="EURUSD", price=1.14143,
                  sl=1.135, tp=1.15):
    return {
        "action": FakeMt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": units / UNITS_PER_LOT,   # server.py sets normalized lots here
        "type": 0 if side == "buy" else 1,
        "price": price,                     # server.py passes live tick; cleared for Market Exec
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 123456,
        "comment": "aether-demo",
        "type_time": 0,
        "type_filling": 2,                  # server.py pre-sets RETURN; overridden in execute
        "requested_units": units,
        "calculated_lots": units / UNITS_PER_LOT,
        "spread_at_entry": 0.0003,
    }


def test_split_helpers():
    assert _order_check_passed(_FakeCheck(0)) is True
    assert _order_check_passed(_FakeCheck(10018)) is False
    assert _order_send_succeeded(FakeMt5, _FakeResult(10009)) is True
    assert _order_send_succeeded(FakeMt5, _FakeResult(10008)) is True
    assert _order_send_succeeded(FakeMt5, _FakeResult(10010)) is True
    assert _order_send_succeeded(FakeMt5, _FakeResult(0)) is False      # 0 != success
    assert _order_send_succeeded(FakeMt5, _FakeResult(10018)) is False  # INVALID_FILL


def test_fok_market_execution_success():
    # This is the REAL broker's symbol: filling_mode=1 (FOK flag),
    # trade_exemode=2 (Market Execution). FOK is tried; price is cleared to 0
    # for Market Execution; order_send accepts -> one position, no RETURN.
    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=1, trade_exemode=2)
    req = _make_request()
    res = execute_demo_order(mt5, req, "EURUSD", broker_mode="demo")
    # FOK tried first (and only, since filling_mode=1), succeeds.
    assert mt5.sends == [FakeMt5.ORDER_FILLING_FOK]
    assert res["status"] == "filled"
    assert res["mt5_retcode"] == 10009
    assert res["type_filling_used"] == FakeMt5.ORDER_FILLING_FOK
    assert mt5.opens == 1


def test_market_execution_request_keeps_live_price_and_no_leak():
    # The sanitized MqlTradeRequest for a TRADE_ACTION_DEAL keeps the live price
    # (the Python wrapper requires a positive price; price=0 makes order_send
    # return None) and carries ONLY valid MqlTradeRequest keys (debug stripped).
    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=1, trade_exemode=2)
    execute_demo_order(mt5, _make_request(), "EURUSD", broker_mode="demo")
    sent = mt5.send_requests[0]
    assert sent["price"] == 1.14143     # live tick passed by server.py
    assert sent["type_filling"] == FakeMt5.ORDER_FILLING_FOK
    assert sent["volume"] == 0.02
    for bad in ("requested_units", "calculated_lots", "spread_at_entry"):
        assert bad not in sent
    for k in ("action", "symbol", "volume", "type", "price", "sl", "tp",
              "deviation", "magic", "comment", "type_time", "type_filling"):
        assert k in sent


class FakeMt5FokRejected(FakeMt5):
    """Variant: broker rejects FOK with UNSUPPORTED_FILLING_MODE (10030) but
    accepts IOC — forces a real fall-through-from-FOK-to-IOC with a fill.
    NOTE: 10018 (MARKET_CLOSED) is terminal and must NOT trigger a fallback;
    only 10030 may."""

    def order_check(self, request):
        # Accept everything at check; the FOK rejection happens at send.
        self.check_requests.append(dict(request))
        return _FakeCheck(retcode=0, comment="done")

    def order_send(self, request):
        self.send_requests.append(dict(request))
        filling = request.get("type_filling")
        self.sends.append(filling)
        if filling == self.ORDER_FILLING_FOK:
            self._last_error = {"code": self.TRADE_RETCODE_UNSUPPORTED_FILLING_MODE,
                                "description": "unsupported filling mode"}
            return _FakeResult(retcode=self.TRADE_RETCODE_UNSUPPORTED_FILLING_MODE)
        self.opens += 1
        return _FakeResult(retcode=self.TRADE_RETCODE_DONE)


def test_fok_rejected_falls_through_to_ioc_success():
    # Symbol lists both FOK and IOC (filling_mode=3). FOK is tried first but the
    # broker rejects it (10030, unsupported filling mode) -> fall through to IOC,
    # which succeeds. Exactly one position. FOK reached order_send (rejected) and
    # IOC then succeeded. A 10018 (MARKET_CLOSED) result would be terminal and
    # must NOT fall through.
    mt5 = FakeMt5FokRejected()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=3, trade_exemode=2)
    res = execute_demo_order(mt5, _make_request(), "EURUSD", broker_mode="demo")
    assert mt5.sends == [FakeMt5.ORDER_FILLING_FOK, FakeMt5.ORDER_FILLING_IOC]
    assert res["status"] == "filled"
    assert res["type_filling_used"] == FakeMt5.ORDER_FILLING_IOC
    assert mt5.opens == 1


def test_ioc_only_symbol_rejected_cleanly():
    # Symbol lists IOC only (filling_mode=2) but the broker rejects IOC (10030).
    # No other candidate exists, so the order is cleanly rejected with no
    # order_send (no double-fill, no RETURN fallback).
    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=2, trade_exemode=2)
    res = execute_demo_order(mt5, _make_request(), "EURUSD", broker_mode="demo")
    assert res["status"] == "rejected"
    assert mt5.sends == []  # nothing reached order_send
    assert res["type_filling_used"] is None


def test_volume_units_to_lots():
    assert UNITS_PER_LOT == 100000.0
    from bridge_validation import normalize_volume, VolumeInfo
    v = VolumeInfo(0.01, 0.01, 500.0)
    norm = normalize_volume(2000, v)
    assert norm["valid"] is True
    assert norm["normalized_lots"] == 0.02
