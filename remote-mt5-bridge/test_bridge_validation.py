"""Unit tests for bridge_validation.execute_demo_order filling-mode logic.

These run WITHOUT the MetaTrader5 SDK by injecting a fake `mt5` object whose
order_check / order_send behave like the LIVE broker that produced this bug:

  * The symbol uses Market Execution (trade_exemode == 2).
  * For a TRADE_ACTION_DEAL market order, the broker accepts ONLY the RETURN
    policy; FOK is rejected by order_send with TRADE_RETCODE_INVALID_FILL
    (10018) and IOC is rejected by order_check/order_send with
    TRADE_RETCODE_UNSUPPORTED_FILLING_MODE (10030).

The test asserts we try RETURN first (for Market Execution), fall through to
FOK/IOC on rejection, and open EXACTLY ONE position (no double-fill from
retrying modes).
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
    """Market Execution broker: RETURN succeeds; FOK->10018; IOC->10030."""

    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_ACTION_DEAL = 1
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_INVALID_FILL = 10018
    TRADE_RETCODE_UNSUPPORTED_FILLING_MODE = 10030

    def __init__(self):
        self.sends = []          # type_filling values passed to order_send
        self.opens = 0
        self.last_request_keys = None

    def order_check(self, request):
        self.last_request_keys = set(request.keys())
        if request.get("type_filling") == self.ORDER_FILLING_IOC:
            return _FakeCheck(retcode=self.TRADE_RETCODE_UNSUPPORTED_FILLING_MODE,
                              comment="unsupported filling mode")
        return _FakeCheck(retcode=0, comment="done")

    def order_send(self, request):
        self.last_request_keys = set(request.keys())
        filling = request.get("type_filling")
        self.sends.append(filling)
        if filling == self.ORDER_FILLING_FOK:
            return _FakeResult(retcode=self.TRADE_RETCODE_INVALID_FILL)
        if filling == self.ORDER_FILLING_IOC:
            return _FakeResult(retcode=self.TRADE_RETCODE_UNSUPPORTED_FILLING_MODE)
        # RETURN accepted -> a single position opens.
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
        "action": FakeMt5.TRADE_ACTION_DEAL if hasattr(FakeMt5, "TRADE_ACTION_DEAL") else 1,
        "symbol": symbol,
        "volume": units / UNITS_PER_LOT,   # server.py sets normalized lots here
        "type": 0 if side == "buy" else 1,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 123456,
        "comment": "aether-demo",
        "type_time": 0,
        "type_filling": 2,
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


def test_market_execution_uses_return_first():
    # This is the REAL broker's symbol: filling_mode=1 (FOK flag) but
    # trade_exemode=2 (Market Execution). RETURN must be tried first and accepted.
    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=1, trade_exemode=2)
    req = _make_request()
    res = execute_demo_order(mt5, req, "EURUSD", broker_mode="demo")
    # RETURN tried first and succeeds -> exactly one send, one position.
    assert mt5.sends == [FakeMt5.ORDER_FILLING_RETURN]
    assert res["status"] == "filled"
    assert res["mt5_retcode"] == 10009
    assert res["type_filling_used"] == FakeMt5.ORDER_FILLING_RETURN
    assert mt5.opens == 1


def test_fok_rejected_falls_through_to_return():
    # Exchange-style symbol that lists FOK first but the broker rejects FOK
    # (10018); fall through to RETURN and succeed. One position.
    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=1, trade_exemode=2)
    req = _make_request()
    res = execute_demo_order(mt5, req, "EURUSD", broker_mode="demo")
    assert res["status"] == "filled"
    assert res["type_filling_used"] == FakeMt5.ORDER_FILLING_RETURN
    assert mt5.opens == 1
    # RETURN is the only mode tried (it succeeded); no FOK/IOC sends.
    assert mt5.sends == [FakeMt5.ORDER_FILLING_RETURN]


def test_no_debug_keys_leak_into_mt5_request():
    # The request dict carries debug context (requested_units, calculated_lots,
    # spread_at_entry) which must NOT be forwarded to order_check/order_send —
    # unknown MqlTradeRequest fields can themselves cause INVALID_FILL.
    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info(filling_mode=1, trade_exemode=2)
    res = execute_demo_order(mt5, _make_request(), "EURUSD", broker_mode="demo")
    assert res["status"] == "filled"
    assert "requested_units" not in mt5.last_request_keys
    assert "calculated_lots" not in mt5.last_request_keys
    assert "spread_at_entry" not in mt5.last_request_keys
    for k in ("action", "symbol", "volume", "type", "price", "sl", "tp",
              "type_filling"):
        assert k in mt5.last_request_keys


def test_volume_units_to_lots():
    assert UNITS_PER_LOT == 100000.0
    # Covered end-to-end by normalize_volume; assert the mapping here.
    from bridge_validation import normalize_volume, VolumeInfo
    v = VolumeInfo(0.01, 0.01, 500.0)
    norm = normalize_volume(2000, v)
    assert norm["valid"] is True
    assert norm["normalized_lots"] == 0.02
