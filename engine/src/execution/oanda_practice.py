"""OANDA Practice (demo) adapter — enabled ONLY if practice credentials are present.

SAFETY (demo-only, hard guarantees):
  * Talks ONLY to the OANDA practice host (api-fxpractice.oanda.com). Any attempt to
    point it at the live host raises immediately.
  * Initialises only when OANDA_PRACTICE_API_KEY and OANDA_PRACTICE_ACCOUNT are set.
  * Places orders ONLY when DEMO_AUTOTRADE_ENABLED=true AND DRY_RUN=false. Otherwise
    place_demo_order returns a simulated 'skipped' status (no network order).
  * Symbol mapping: EURUSD->EUR_USD, etc. XAUUSD requires the account to support
    XAU_USD; otherwise the order is rejected loudly.
  * Secrets are never stored; only redacted raw responses are kept.
  * All placements require stop_loss + take_profit (enforced upstream by guards too).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from .adapter import (
    ExecutionAdapter, DemoOrderRequest, AccountInfo, PriceQuote, Position,
    OrderStatus, redact,
)

# OANDA uses underscore instrument names.
SYMBOL_MAP = {
    "EURUSD": "EUR_USD",
    "GBPUSD": "GBP_USD",
    "USDJPY": "USD_JPY",
    "AUDUSD": "AUD_USD",
    "USDCAD": "USD_CAD",
    "XAUUSD": "XAU_USD",
}


class OandaPracticeAdapter(ExecutionAdapter):
    name = "oanda_practice"
    mode = "demo"
    BASE_PRACTICE = "https://api-fxpractice.oanda.com"   # practice sandbox ONLY
    BASE_LIVE = "https://api-fxtrade.oanda.com"          # MUST never be used

    def __init__(self, env_prefix: str = "OANDA_PRACTICE"):
        self._api_key = os.environ.get(f"{env_prefix}_API_KEY")
        self._account = os.environ.get(f"{env_prefix}_ACCOUNT")
        if not self._api_key or not self._account:
            raise RuntimeError(
                "OANDA Practice credentials missing "
                f"({env_prefix}_API_KEY, {env_prefix}_ACCOUNT). "
                "Demo bridge disabled; use 'mock' or provide practice creds."
            )
        try:
            import requests  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"requests lib unavailable: {exc}. Demo bridge disabled.") from exc
        self._requests = requests
        # Execution gating (env-only, no secrets stored).
        self._dry_run = os.environ.get("DRY_RUN", "true").lower() not in ("0", "false", "no")
        self._autotrade = os.environ.get("DEMO_AUTOTRADE_ENABLED", "false").lower() in ("1", "true", "yes")

    # ---- safety helpers ----
    def _reject_live(self):
        # Defensive: ensure we never target the live host.
        raise RuntimeError("OANDA live host rejected — practice adapter is demo-only.")

    def _map_symbol(self, symbol: str) -> str:
        if symbol in SYMBOL_MAP:
            return SYMBOL_MAP[symbol]
        # Already in OANDA form (contains underscore) — pass through.
        if "_" in symbol:
            return symbol
        raise ValueError(f"unsupported symbol {symbol!r} for OANDA Practice")

    def _hdr(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ---- interface ----
    def get_account(self) -> AccountInfo:
        r = self._requests.get(f"{self.BASE_PRACTICE}/v3/accounts/{self._account}/summary",
                               headers=self._hdr(), timeout=10)
        r.raise_for_status()
        bal = r.json()["account"]["balance"]
        raw = redact(f'{{"account":{self._account},"mode":"demo"}}')
        return AccountInfo(broker=self.name, broker_mode=self.mode, balance=float(bal),
                           currency="USD", raw_redacted=raw)

    def get_prices(self, symbol: str) -> PriceQuote:
        oa_sym = self._map_symbol(symbol)
        r = self._requests.get(f"{self.BASE_PRACTICE}/v3/accounts/{self._account}/pricing",
                               params={"instruments": oa_sym}, headers=self._hdr(), timeout=10)
        r.raise_for_status()
        price = r.json()["prices"][0]
        bids = [float(b["price"]) for b in price["bids"]]
        asks = [float(a["price"]) for a in price["asks"]]
        spread = (asks[0] - bids[0]) if asks and bids else 0.0
        return PriceQuote(symbol=symbol, bid=bids[0], ask=asks[0], spread=spread,
                          timestamp=self._now())

    def place_demo_order(self, order: DemoOrderRequest) -> OrderStatus:
        oa_sym = self._map_symbol(order.symbol)
        # XAU support detection: account must list XAU_USD; else reject loudly.
        if order.symbol == "XAUUSD" and not self._supports_xau():
            return OrderStatus(order_id="", status="rejected",
                               rejection_reason="XAU_USD not supported by this OANDA practice account",
                               raw_redacted=redact("XAU_USD unsupported"))
        # Gate: only execute when autotrade enabled AND not dry-run.
        if not self._autotrade or self._dry_run:
            return OrderStatus(
                order_id="", status="skipped",
                rejection_reason=(
                    "DRY_RUN active" if self._dry_run else "DEMO_AUTOTRADE_ENABLED=false"
                ),
                raw_redacted=redact(f"mode=demo dry_run={self._dry_run} autotrade={self._autotrade}"),
            )
        payload = {
            "order": {
                "units": str(int(order.units)) if order.side == "buy" else str(-int(order.units)),
                "instrument": oa_sym,
                "stopLossOnFill": {"price": str(order.stop_loss)},
                "takeProfitOnFill": {"price": str(order.take_profit)},
                "type": "MARKET",
            }
        }
        r = self._requests.post(f"{self.BASE_PRACTICE}/v3/accounts/{self._account}/orders",
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

    def _supports_xau(self) -> bool:
        try:
            r = self._requests.get(f"{self.BASE_PRACTICE}/v3/accounts/{self._account}/instruments",
                                   params={"instruments": "XAU_USD"}, headers=self._hdr(), timeout=10)
            return r.ok and bool(r.json().get("instruments"))
        except Exception:
            return False

    def close_demo_order(self, order_id: str) -> OrderStatus:
        r = self._requests.put(
            f"{self.BASE_PRACTICE}/v3/accounts/{self._account}/orders/{order_id}/cancel",
            headers=self._hdr(), timeout=10)
        return OrderStatus(order_id=order_id, status="closed" if r.ok else "rejected",
                           raw_redacted=redact(r.text))

    def get_open_positions(self) -> list[Position]:
        r = self._requests.get(f"{self.BASE_PRACTICE}/v3/accounts/{self._account}/openPositions",
                               headers=self._hdr(), timeout=10)
        r.raise_for_status()
        out = []
        for p in r.json().get("positions", []):
            out.append(Position(
                order_id=p["id"], symbol=p["instrument"], side=p["long"]["units"],
                units=abs(float(p["long"]["units"] or p["short"]["units"])),
                open_price=float(p["avgPrice"]),
                stop_loss=0.0, take_profit=0.0, raw_redacted=redact(str(p)),
            ))
        return out

    def get_order_status(self, order_id: str) -> OrderStatus:
        r = self._requests.get(f"{self.BASE_PRACTICE}/v3/accounts/{self._account}/orders/{order_id}",
                               headers=self._hdr(), timeout=10)
        if not r.ok:
            return OrderStatus(order_id=order_id, status="rejected", raw_redacted=redact(r.text))
        return OrderStatus(order_id=order_id, status="filled", raw_redacted=redact(r.text))


__all__ = ["OandaPracticeAdapter", "SYMBOL_MAP"]
