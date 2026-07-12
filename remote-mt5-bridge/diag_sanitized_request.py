"""No-secrets diagnostic: inspect the exact sanitized MqlTradeRequest that
execute_demo_order builds and sends to order_check/order_send, WITHOUT the
MetaTrader5 SDK and WITHOUT any credentials.

Models this symbol:
  * filling_mode = 1  -> SYMBOL_FILLING_FOK flag  (FOK only)
  * trade_exemode = 2 -> SYMBOL_TRADE_EXECUTION_MARKET (Market Execution)
  * TRADE_ACTION_DEAL market order

For Market Execution the bridge must send price=0 (terminal fills at market).
The diagnostic echoes the sanitized request (only valid MqlTradeRequest keys),
the chosen filling mode, and a simulated mt5.last_error() so we can compare
against the official Market Execution requirements before deploying.

Run:  python3 diag_sanitized_request.py
"""
from __future__ import annotations

# Mirror the candidate logic WITHOUT RETURN (RETURN is invalid for Market Exec).
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
TRADE_ACTION_DEAL = 1
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_INVALID_FILL = 10018
TRADE_RETCODE_UNSUPPORTED_FILLING_MODE = 10030

_MT5_REQ_KEYS = {
    "action", "symbol", "volume", "type", "price", "sl", "tp",
    "deviation", "magic", "comment", "type_time", "type_filling",
    "position", "position_by",
}


class _Err:
    code = -1
    description = "order_send returned None (simulated): price=0 makes the MT5 Python wrapper reject the request"


class FakeMt5:
    ORDER_FILLING_FOK = ORDER_FILLING_FOK
    ORDER_FILLING_IOC = ORDER_FILLING_IOC
    ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
    TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
    TRADE_RETCODE_DONE = TRADE_RETCODE_DONE
    TRADE_RETCODE_INVALID_FILL = TRADE_RETCODE_INVALID_FILL
    TRADE_RETCODE_UNSUPPORTED_FILLING_MODE = TRADE_RETCODE_UNSUPPORTED_FILLING_MODE

    def __init__(self):
        self.sent = []

    def last_error(self):
        return _Err()

    def order_check(self, request):
        # Echo the sanitized request as seen by MT5 (no secrets).
        self.sent.append(("order_check", {k: request[k] for k in request}))
        from types import SimpleNamespace
        return SimpleNamespace(retcode=0, comment="done")

    def order_send(self, request):
        self.sent.append(("order_send", {k: request[k] for k in request}))
        err = self.last_error()
        from types import SimpleNamespace
        return SimpleNamespace(retcode=err.code, comment=err.description)


def _symbol_info():
    class S:
        pass
    s = S()
    s.filling_mode = 1     # SYMBOL_FILLING_FOK only
    s.trade_exemode = 2    # SYMBOL_TRADE_EXECUTION_MARKET
    s.volume_min = 0.01
    s.volume_step = 0.01
    s.volume_max = 500.0
    return s


def main():
    import sys
    sys.path.insert(0, ".")
    from bridge_validation import execute_demo_order

    mt5 = FakeMt5()
    mt5.symbol_info = lambda m: _symbol_info()
    request = {
        "action": TRADE_ACTION_DEAL,
        "symbol": "EURUSD",
        "volume": 0.02,         # 2000 units / 100000
        "type": 0,              # ORDER_TYPE_BUY
        "price": 1.14143,       # server.py passes the live tick here
        "sl": 1.135,
        "tp": 1.15,
        "deviation": 10,
        "magic": 123456,
        "comment": "aether-demo",
        "type_time": 0,         # ORDER_TIME_GTC
        "type_filling": 2,      # server.py pre-sets RETURN (will be overridden)
        # debug/context keys that must NOT be forwarded:
        "requested_units": 2000,
        "calculated_lots": 0.02,
        "spread_at_entry": 0.0003,
    }
    res = execute_demo_order(mt5, request, "EURUSD", broker_mode="demo")

    print("=== SANITIZED REQUESTS SEEN BY MT5 (no secrets) ===")
    for stage, req in mt5.sent:
        print(f"\n[{stage}]")
        for k in ("action", "symbol", "volume", "type", "price", "sl", "tp",
                  "deviation", "magic", "comment", "type_time", "type_filling"):
            mark = "" if k in _MT5_REQ_KEYS else "  <-- INVALID KEY"
            print(f"  {k:14}= {req.get(k)!r}{mark}")
        leaked = set(req.keys()) - _MT5_REQ_KEYS
        if leaked:
            print(f"  !! LEAKED NON-MT5 KEYS: {sorted(leaked)}")
        else:
            print("  (clean: only valid MqlTradeRequest keys)")

    print("\n=== RESULT ===")
    # Print the relevant fields without secrets.
    for k in ("status", "mt5_retcode", "mt5_retcode_name", "mt5_comment",
              "mt5_last_error", "type_filling_used", "type_filling_name",
              "sent_volume", "filling_mode_candidates", "symbol_filling_mode"):
        if k in res:
            print(f"  {k} = {res[k]!r}")


if __name__ == "__main__":
    main()
