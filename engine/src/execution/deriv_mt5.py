"""Deriv MT5 demo adapter — enabled ONLY if an MT5 terminal + credentials exist.

SAFETY: This adapter talks to a DEMO account only. It refuses to initialise if
credentials are absent, and it can only ever operate in broker_mode='demo'.
It is intentionally lightweight: if the optional deps (MetaTrader5) or creds are
missing it raises at construction time so the caller can fall back to 'mock' and
keep the demo bridge disabled unless explicitly selected.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from .adapter import (
    ExecutionAdapter,
    DemoOrderRequest,
    AccountInfo,
    PriceQuote,
    Position,
    OrderStatus,
    redact,
)


def _env(prefix: str) -> dict:
    return {
        "login": os.environ.get(f"{prefix}_LOGIN"),
        "password": os.environ.get(f"{prefix}_PASSWORD"),
        "server": os.environ.get(f"{prefix}_SERVER"),
    }


class DerivMT5DemoAdapter(ExecutionAdapter):
    name = "deriv_mt5"
    mode = "demo"

    def __init__(self, env_prefix: str = "DERIV_MT5"):
        creds = _env(env_prefix)
        if not all(creds.values()):
            missing = [k for k, v in creds.items() if not v]
            raise RuntimeError(
                "Deriv MT5 demo credentials missing ("
                + ", ".join(f"{env_prefix}_{k.upper()}" for k in missing)
                + "). Keeping demo bridge disabled; use 'mock' or provide creds."
            )
        # Defer heavy import so tests without MetaTrader5 don't crash on import.
        try:
            import MetaTrader5  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on host
            raise RuntimeError(f"MT5 terminal/SDK unavailable: {exc}. Demo bridge disabled.") from exc
        self._mt5 = MetaTrader5
        self._creds = creds
        self._connected = False

    def _ensure(self):
        if not self._connected:
            authorized = self._mt5.login(
                int(self._creds["login"]), self._creds["password"], self._creds["server"]
            )
            if not authorized:
                raise RuntimeError("Deriv MT5 demo login failed — demo bridge disabled.")
            self._connected = True

    def get_account(self) -> AccountInfo:
        self._ensure()
        info = self._mt5.account_info()
        raw = redact(f'{{"login":{info.login},"mode":"demo"}}')
        return AccountInfo(broker=self.name, broker_mode=self.mode,
                           balance=float(info.balance), currency=str(info.currency or "USD"),
                           raw_redacted=raw)

    def get_prices(self, symbol: str) -> PriceQuote:
        self._ensure()
        tick = self._mt5.symbol_info_tick(symbol)
        spread = (tick.ask - tick.bid) if tick else 0.0
        return PriceQuote(symbol=symbol, bid=float(tick.bid), ask=float(tick.ask),
                          spread=float(spread), timestamp=self._now())

    def place_demo_order(self, order: DemoOrderRequest) -> OrderStatus:
        self._ensure()
        # NOTE: only demo orders; no real-money path exists.
        raise NotImplementedError("MT5 demo placement requires host terminal; not executed here.")

    def close_demo_order(self, order_id: str) -> OrderStatus:
        self._ensure()
        raise NotImplementedError("MT5 demo close requires host terminal.")

    def get_open_positions(self) -> list[Position]:
        self._ensure()
        return []

    def get_order_status(self, order_id: str) -> OrderStatus:
        self._ensure()
        return OrderStatus(order_id=order_id, status="pending", raw_redacted="demo")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


# Imported lazily in factory to avoid import errors on hosts without deps.
__all__ = ["DerivMT5DemoAdapter"]
