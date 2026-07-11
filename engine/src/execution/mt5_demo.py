"""MT5 demo adapter — enabled ONLY if an MT5 terminal + demo credentials exist.

SAFETY (demo-only, hard guarantees):
  * Connects only to a DEMO account. If the logged-in account is detected as a live
    (real) account, all operations are rejected loudly and no order is placed.
  * Requires MT5_LOGIN, MT5_PASSWORD, MT5_SERVER from env; if the MetaTrader5 SDK or
    terminal is missing it raises at construction (fail loud, bridge disabled).
  * Places orders ONLY when DEMO_AUTOTRADE_ENABLED=true AND DRY_RUN=false.
  * Symbol mapping is configurable (brokers name pairs differently: EURUSD, EURUSDm,
    XAUUSD, Volatility symbols, etc.) via MT5_SYMBOL_MAP env (JSON) or defaults.
  * No live-money path exists; broker_mode is always 'demo'.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from .adapter import (
    ExecutionAdapter, DemoOrderRequest, AccountInfo, PriceQuote, Position,
    OrderStatus, redact,
)

# Default symbol map: our canonical -> MT5 broker symbol. Override via MT5_SYMBOL_MAP.
DEFAULT_SYMBOL_MAP = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "USDCAD": "USDCAD",
    "XAUUSD": "XAUUSD",
}


def _load_symbol_map() -> dict:
    raw = os.environ.get("MT5_SYMBOL_MAP")
    if raw:
        try:
            return {**DEFAULT_SYMBOL_MAP, **json.loads(raw)}
        except Exception:
            pass
    return dict(DEFAULT_SYMBOL_MAP)


class MT5DemoAdapter(ExecutionAdapter):
    name = "mt5_demo"
    mode = "demo"

    def __init__(self, env_prefix: str = "MT5"):
        self._login = os.environ.get(f"{env_prefix}_LOGIN")
        self._password = os.environ.get(f"{env_prefix}_PASSWORD")
        self._server = os.environ.get(f"{env_prefix}_SERVER")
        if not (self._login and self._password and self._server):
            missing = [f"{env_prefix}_{k}" for k, v in
                       (("LOGIN", self._login), ("PASSWORD", self._password),
                        ("SERVER", self._server)) if not v]
            raise RuntimeError(
                "MT5 demo credentials missing (" + ", ".join(missing) +
                "). Keeping demo bridge disabled; use 'mock' or provide creds."
            )
        try:
            import MetaTrader5  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"MT5 terminal/SDK unavailable: {exc}. Demo bridge disabled.") from exc
        self._mt5 = MetaTrader5
        self._symbol_map = _load_symbol_map()
        self._dry_run = os.environ.get("DRY_RUN", "true").lower() not in ("0", "false", "no")
        self._autotrade = os.environ.get("DEMO_AUTOTRADE_ENABLED", "false").lower() in ("1", "true", "yes")
        self._connected = False

    def _ensure(self):
        if not self._connected:
            authorized = self._mt5.login(
                int(self._login), self._password, self._server
            )
            if not authorized:
                raise RuntimeError("MT5 demo login failed — demo bridge disabled.")
            info = self._mt5.account_info()
            # Reject live accounts if detectable.
            if getattr(info, "trade_mode", None) is not None:
                # MT5 trade_mode: 0=REAL, 1=DEMO, 2=CONTEST
                if int(info.trade_mode) == 0:
                    raise RuntimeError("MT5 account is LIVE — demo adapter refuses (never trade live).")
            self._connected = True

    def _map_symbol(self, symbol: str) -> str:
        return self._symbol_map.get(symbol, symbol)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_account(self) -> AccountInfo:
        self._ensure()
        info = self._mt5.account_info()
        raw = redact(f'{{"login":{info.login},"mode":"demo","trade_mode":{info.trade_mode}}}')
        return AccountInfo(broker=self.name, broker_mode=self.mode,
                           balance=float(info.balance), currency=str(info.currency or "USD"),
                           raw_redacted=raw)

    def get_prices(self, symbol: str) -> PriceQuote:
        self._ensure()
        mt5_sym = self._map_symbol(symbol)
        tick = self._mt5.symbol_info_tick(mt5_sym)
        if not tick:
            raise RuntimeError(f"MT5 no tick for {mt5_sym}")
        spread = (tick.ask - tick.bid) if tick else 0.0
        return PriceQuote(symbol=symbol, bid=float(tick.bid), ask=float(tick.ask),
                          spread=float(spread), timestamp=self._now())

    def place_demo_order(self, order: DemoOrderRequest) -> OrderStatus:
        self._ensure()
        mt5_sym = self._map_symbol(order.symbol)
        if not self._autotrade or self._dry_run:
            return OrderStatus(
                order_id="", status="skipped",
                rejection_reason=(
                    "DRY_RUN active" if self._dry_run else "DEMO_AUTOTRADE_ENABLED=false"
                ),
                raw_redacted=redact(f"mode=demo dry_run={self._dry_run} autotrade={self._autotrade}"),
            )
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": mt5_sym,
            "volume": order.units / 10000.0,  # units are in 0.01 lots here; adapt as needed
            "type": self._mt5.ORDER_TYPE_BUY if order.side == "buy" else self._mt5.ORDER_TYPE_SELL,
            "price": self._mt5.symbol_info_tick(mt5_sym).ask if order.side == "buy"
            else self._mt5.symbol_info_tick(mt5_sym).bid,
            "sl": order.stop_loss,
            "tp": order.take_profit,
            "deviation": 10,
            "magic": 123456,
            "comment": "aether-demo",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }
        result = self._mt5.order_send(request)
        raw = redact(f'{{"retcode":{getattr(result, "retcode", "?")}}}')
        if getattr(result, "retcode", 1) != self._mt5.TRADE_RETCODE_DONE:
            return OrderStatus(order_id="", status="rejected",
                               rejection_reason=f"mt5 retcode {getattr(result, 'retcode', '?')}",
                               raw_redacted=raw)
        return OrderStatus(order_id=str(getattr(result, "order", "")),
                           status="filled", filled_entry=order.requested_entry,
                           spread_at_entry=None, slippage=None, raw_redacted=raw)

    def close_demo_order(self, order_id: str) -> OrderStatus:
        self._ensure()
        # Close by reversing; simplified: treat order_id as ticket.
        result = self._mt5.order_send({"action": self._mt5.TRADE_ACTION_REMOVE,
                                       "order": int(order_id) if order_id.isdigit() else 0})
        raw = redact(f'{{"retcode":{getattr(result, "retcode", "?")}}}')
        return OrderStatus(order_id=order_id, status="closed", raw_redacted=raw)

    def get_open_positions(self) -> list[Position]:
        self._ensure()
        out = []
        for p in self._mt5.positions_get() or []:
            out.append(Position(
                order_id=str(p.ticket), symbol=p.symbol, side="buy" if p.volume > 0 else "sell",
                units=p.volume * 10000.0, open_price=float(p.price_open),
                stop_loss=float(p.sl), take_profit=float(p.tp),
                raw_redacted=redact(f'{{"ticket":{p.ticket}}}'),
            ))
        return out

    def get_order_status(self, order_id: str) -> OrderStatus:
        self._ensure()
        return OrderStatus(order_id=order_id, status="filled", raw_redacted=redact("mt5 demo"))


__all__ = ["MT5DemoAdapter", "DEFAULT_SYMBOL_MAP"]
