"""OANDA Practice adapter — enabled ONLY if practice credentials are present.

SAFETY: Practice/demo account only. Initialises only when OANDA_PRACTICE_API_KEY
and OANDA_PRACTICE_ACCOUNT are set; otherwise it raises so the bridge stays
disabled and falls back to 'mock'. No live account is ever targeted.
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


class OandaPracticeAdapter(ExecutionAdapter):
    name = "oanda_practice"
    mode = "demo"
    BASE = "https://api-fxpractice.oanda.com"   # practice sandbox only

    def __init__(self, env_prefix: str = "OANDA_PRACTICE"):
        self._api_key = os.environ.get(f"{env_prefix}_API_KEY")
        self._account = os.environ.get(f"{env_prefix}_ACCOUNT")
        if not self._api_key or not self._account:
            raise RuntimeError(
                "OANDA Practice credentials missing "
                f"({env_prefix}_API_KEY, {env_prefix}_ACCOUNT). "
                "Demo bridge disabled; use 'mock' or provide practice creds."
            )
        # Defer heavy HTTP import so missing deps don't break import on tests.
        try:
            import requests  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"requests lib unavailable: {exc}. Demo bridge disabled.") from exc
        self._requests = requests

    def _hdr(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def get_account(self) -> AccountInfo:
        r = self._requests.get(f"{self.BASE}/v3/accounts/{self._account}/summary",
                               headers=self._hdr(), timeout=10)
        r.raise_for_status()
        bal = r.json()["account"]["balance"]
        raw = redact(f'{{"account":{self._account},"mode":"demo","auth":"Bearer {self._api_key}"}}')
        return AccountInfo(broker=self.name, broker_mode=self.mode, balance=float(bal),
                           currency="USD", raw_redacted=raw)

    def get_prices(self, symbol: str) -> PriceQuote:
        r = self._requests.get(f"{self.BASE}/v3/accounts/{self._account}/pricing",
                               params={"instruments": symbol}, headers=self._hdr(), timeout=10)
        r.raise_for_status()
        price = r.json()["prices"][0]
        bids = [float(b["price"]) for b in price["bids"]]
        asks = [float(a["price"]) for a in price["asks"]]
        spread = (asks[0] - bids[0]) if asks and bids else 0.0
        return PriceQuote(symbol=symbol, bid=bids[0], ask=asks[0], spread=spread,
                          timestamp=self._now())

    def place_demo_order(self, order: DemoOrderRequest) -> OrderStatus:
        # Practice order submission. Demo-only endpoint (BASE is practice host).
        payload = {
            "order": {
                "units": str(int(order.units)) if order.side == "buy" else str(-int(order.units)),
                "instrument": order.symbol,
                "stopLossOnFill": {"price": str(order.stop_loss)},
                "takeProfitOnFill": {"price": str(order.take_profit)},
                "type": "MARKET",
            }
        }
        r = self._requests.post(f"{self.BASE}/v3/accounts/{self._account}/orders",
                                headers=self._hdr(), json=payload, timeout=10)
        raw = redact(r.text)
        if r.status_code >= 400:
            return OrderStatus(order_id="", status="rejected",
                               rejection_reason=f"practice rejection {r.status_code}",
                               raw_redacted=raw)
        body = r.json()
        oid = body.get("orderCreateTransaction", {}).get("id", "")
        return OrderStatus(order_id=oid, status="filled",
                           filled_entry=order.requested_entry,
                           spread_at_entry=None, slippage=None, raw_redacted=raw)

    def close_demo_order(self, order_id: str) -> OrderStatus:
        r = self._requests.put(f"{self.BASE}/v3/accounts/{self._account}/orders/{order_id}/cancel",
                               headers=self._hdr(), timeout=10)
        return OrderStatus(order_id=order_id, status="closed" if r.ok else "rejected",
                           raw_redacted=redact(r.text))

    def get_open_positions(self) -> list[Position]:
        r = self._requests.get(f"{self.BASE}/v3/accounts/{self._account}/openPositions",
                               headers=self._hdr(), timeout=10)
        r.raise_for_status()
        out = []
        for p in r.json().get("positions", []):
            out.append(Position(
                order_id=p["id"], symbol=p["instrument"], side=p["long"]["units"],
                units=abs(float(p["long"]["units"]) or p["short"]["units"]),
                open_price=float(p["avgPrice"]),
                stop_loss=0.0, take_profit=0.0, raw_redacted=redact(str(p)),
            ))
        return out

    def get_order_status(self, order_id: str) -> OrderStatus:
        r = self._requests.get(f"{self.BASE}/v3/accounts/{self._account}/orders/{order_id}",
                               headers=self._hdr(), timeout=10)
        if not r.ok:
            return OrderStatus(order_id=order_id, status="rejected", raw_redacted=redact(r.text))
        return OrderStatus(order_id=order_id, status="filled", raw_redacted=redact(r.text))

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = ["OandaPracticeAdapter"]
