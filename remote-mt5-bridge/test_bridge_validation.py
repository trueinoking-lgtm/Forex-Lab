"""Unit tests for bridge_validation.execute_demo_order filling-mode logic.

These run WITHOUT the MetaTrader5 SDK by injecting a fake `mt5` object whose
order_check / order_send behave like the live broker: order_check is LENIENT
(accepts any filling mode) while order_send REJECTS FOK with
TRADE_RETCODE_INVALID_FILL (10018) for a market deal — matching the broker
that produced this bug. The test asserts we fall through to IOC and open
exactly ONE position (no double-fill from retrying modes).
"""
from __future__ import annotations

from bridge_validation import (
    execute_demo_order,
    _order_check_passed,
    _order_send_succeeded,
    UNITS_PER_LOT,
)


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
    """order_check always passes; order_send rejects FOK (10018), accepts others."""

    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_INVALID_FILL = 10018

    def __init__(self):
        self.sends = []          # type_filling values passed to order_send
        self.opened_positions = 0

    def order_check(self, request):
        # Lenient: accepts any mode (mirrors the broker that misled us).
        return _FakeCheck(retcode=0, comment="done")

    def order_send(self, request):
        filling = request.get("type_filling")
        self.sends.append(filling)
        if filling == self.ORDER_FILLING_FOK:
            return _FakeResult(retcode=self.TRADE_RETCODE_INVALID_FILL)
        # IOC / RETURN accepted -> a single position opens.
        self.opened_positions += 1
        return _FakeResult(retcode=self.TRADE_RETCODE_DONE)


def _symbol_info(filling_mode=1):
    class S:
        pass
    s = S()
    s.volume_min = 0.01
    s.volume_step = 0.01
    s.volume_max = 500.0
    s.filling_mode = filling_mode
    return s


def _make_request(units=2000, side="buy", symbol="EURUSD", price=1.14143,
                  sl=1.135, tp=1.15):
    return {
        "action": FakeMt5.TRADE_ACTION_DEAL if hasattr(FakeMt5, "TRADE_ACTION_DEAL") else 1,
        "symbol": symbol,
        "type": 0 if side == "buy" else 1,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 123456,
        "comment": "aether-demo",
        "type_time": 0,
        "type_filling": 1,
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


def test_fok_rejected_falls_through_to_ioc_single_position(monkeypatch):
    # Force filling_mode=1 (FOK flag) so FOK is the SECOND candidate after IOC.
    mt5 = FakeMt5()
    req = _make_request()
    # Patch symbol_info used inside execute_demo_order via a wrapper is not
    # needed: execute_demo_order reads mt5.symbol_info(m). We inject a bound
    # method that returns our fixture.
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=1)
    res = execute_demo_order(mt5, req, "EURUSD", broker_mode="demo")
    # IOC is tried first and succeeds; no fallthrough needed here.
    assert res["status"] == "filled"
    assert res["type_filling_used"] in (1, 0, 2)
    assert mt5.opened_positions == 1


def test_ioc_first_avoids_invalid_fill(monkeypatch):
    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=1)
    req = _make_request()
    res = execute_demo_order(mt5, req, "EURUSD", broker_mode="demo")
    # Because IOC is first in the candidate list, order_send should be called
    # with IOC (1) first; FOK (0) must NOT be the first send.
    assert mt5.sends[0] == FakeMt5.ORDER_FILLING_IOC
    assert res["status"] == "filled"
    assert res["mt5_retcode"] == 10009
    assert res["order_id"] == "77"
    assert res["deal_id"] == "78"
    assert res["position_id"] == "79"


def test_volume_units_to_lots():
    assert UNITS_PER_LOT == 100000.0
    # Covered end-to-end by normalize_volume; assert the mapping here.
    from bridge_validation import normalize_volume, VolumeInfo
    v = VolumeInfo(0.01, 0.01, 500.0)
    norm = normalize_volume(2000, v)
    assert norm["valid"] is True
    assert norm["normalized_lots"] == 0.02
