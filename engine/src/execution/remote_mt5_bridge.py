"""VPS-side Remote MT5 Bridge adapter (HTTP client to the Windows PC bridge).

The VPS NEVER holds MT5 credentials. It only knows:
  * REMOTE_MT5_BRIDGE_URL  (https://<pc>.tailnet.ts.net, set privately via tailscale serve)
  * REMOTE_MT5_BRIDGE_TOKEN (bearer auth)

All trading happens on the PC bridge, which enforces demo-only + its own
kill switch. This adapter is a thin, fail-loud client.

SAFETY:
  * Raises if REMOTE_MT5_BRIDGE_URL / REMOTE_MT5_BRIDGE_TOKEN are missing.
  * Rejects any response claiming broker_mode != 'demo'.
  * Times out; retries a bounded number of times; fails loud if unreachable.
  * Does NOT fall back to mock for real demo commands (the caller decides that).
  * No secret is stored: only the URL host (not the token) is ever logged,
    and the token is never written to the DB.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import requests  # type: ignore

from .adapter import (
    ExecutionAdapter, DemoOrderRequest, AccountInfo, PriceQuote, Position,
    OrderStatus, redact,
)

DEFAULT_TIMEOUT = 8.0
DEFAULT_RETRIES = 1


class RemoteMT5BridgeAdapter(ExecutionAdapter):
    name = "remote_mt5"
    mode = "demo"

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        self._url = (url or os.environ.get("REMOTE_MT5_BRIDGE_URL") or "").rstrip("/")
        self._token = token or os.environ.get("REMOTE_MT5_BRIDGE_TOKEN") or ""
        if not self._url:
            raise RuntimeError(
                "remote_mt5 unavailable: REMOTE_MT5_BRIDGE_URL not set. "
                "Configure the Tailscale bridge URL (PC side)."
            )
        if not self._token:
            raise RuntimeError(
                "remote_mt5 unavailable: REMOTE_MT5_BRIDGE_TOKEN not set. "
                "Use the same token as the PC bridge .env."
            )
        self._timeout = float(os.environ.get("REMOTE_MT5_BRIDGE_TIMEOUT", DEFAULT_TIMEOUT))
        self._retries = int(os.environ.get("REMOTE_MT5_BRIDGE_RETRIES", DEFAULT_RETRIES))

    # ---- HTTP helper ----
    def _req(self, method: str, path: str, **kw):
        headers = {"Authorization": f"Bearer {self._token}"}
        kw.setdefault("headers", {}).update(headers)
        kw.setdefault("timeout", self._timeout)
        last_err: Optional[Exception] = None
        for attempt in range(self._retries + 1):
            try:
                resp = requests.request(method, f"{self._url}{path}", **kw)
                if resp.status_code == 401:
                    raise RuntimeError("remote_mt5: invalid bearer token (401)")
                if resp.status_code == 403:
                    raise RuntimeError("remote_mt5: token forbidden (403)")
                if resp.status_code >= 500:
                    raise RuntimeError(f"remote_mt5 bridge error {resp.status_code}")
                return resp
            except requests.RequestException as exc:
                last_err = exc
                continue
        raise RuntimeError(f"remote_mt5 unreachable after {self._retries + 1} tries: {last_err}")

    def _assert_demo(self, body: dict) -> None:
        mode = body.get("broker_mode")
        if mode and mode != "demo":
            raise RuntimeError(f"remote_mt5 bridge reports non-demo mode {mode!r} — refusing")

    # ---- interface ----
    def get_account(self) -> AccountInfo:
        resp = self._req("GET", "/account")
        body = resp.json()
        self._assert_demo(body)
        return AccountInfo(
            broker=self.name, broker_mode="demo",
            balance=float(body.get("balance", 0.0)),
            currency=str(body.get("currency", "USD")),
            company=str(body.get("company", "") or ""),
            server=str(body.get("server", "") or ""),
            raw_redacted=redact(json.dumps({k: v for k, v in body.items() if k != "login"})),
        )

    def get_prices(self, symbol: str) -> PriceQuote:
        resp = self._req("GET", f"/quote?symbol={symbol}")
        body = resp.json()
        self._assert_demo(body)
        so = body.get("session_open", None)
        if not isinstance(so, bool):
            so = None
        return PriceQuote(
            symbol=symbol, bid=float(body["bid"]), ask=float(body["ask"]),
            spread=float(body.get("spread", body["ask"] - body["bid"])),
            timestamp=body.get("timestamp", ""),
            session_open=so,
        )

    def place_demo_order(self, order: DemoOrderRequest) -> OrderStatus:
        payload = {
            "symbol": order.symbol, "side": order.side, "units": order.units,
            "stop_loss": order.stop_loss, "take_profit": order.take_profit,
            "signal_id": order.signal_id, "requested_entry": order.requested_entry,
        }
        resp = self._req("POST", "/place-demo-order", json=payload)
        body = resp.json()
        self._assert_demo(body)
        status = body.get("status", "rejected")
        return OrderStatus(
            order_id=str(body.get("order_id", "")), status=status,
            filled_entry=body.get("filled_entry"),
            rejection_reason=body.get("rejection_reason"),
            spread_at_entry=body.get("spread_at_entry"),
            slippage=body.get("slippage"),
            deal_id=str(body.get("deal_id", "")) or None,
            position_id=str(body.get("position_id", "")) or None,
            type_filling_used=body.get("type_filling_used"),
            partial=bool(body.get("partial", False)),
            raw_redacted=redact(json.dumps({k: v for k, v in body.items()
                                            if k not in ("order_id",)})),
        )

    def close_demo_order(self, order_id: str) -> OrderStatus:
        # PC bridge closes via MT5 directly; the VPS records the status.
        return OrderStatus(order_id=order_id, status="closed", raw_redacted="remote_mt5 close")

    def get_open_positions(self) -> list[Position]:
        resp = self._req("GET", "/positions")
        body = resp.json()
        self._assert_demo(body)
        out = []
        for p in body.get("positions", []):
            out.append(Position(
                order_id=str(p["order_id"]), symbol=p["symbol"], side=p["side"],
                units=float(p["units"]), open_price=float(p["open_price"]),
                stop_loss=float(p["stop_loss"]), take_profit=float(p["take_profit"]),
                raw_redacted=redact(json.dumps(p)),
            ))
        return out

    def get_order_status(self, order_id: str) -> OrderStatus:
        resp = self._req("GET", f"/order-status?order_id={order_id}")
        body = resp.json()
        self._assert_demo(body)
        return OrderStatus(order_id=order_id, status=body.get("status", "filled"),
                          raw_redacted="remote_mt5 status")


__all__ = ["RemoteMT5BridgeAdapter"]
