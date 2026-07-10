"""Deterministic mock demo adapter — used for tests and as the safe default.

No network. Fills are derived deterministically from the requested entry and a
configurable (but fixed) spread/slippage so forward-test results are reproducible.
It simulates broker behaviour: rejections, partial slippage, and rejects any
order whose mode is not 'demo' (defence-in-depth — the guard also blocks this).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
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


@dataclass
class MockConfig:
    """Deterministic market simulation parameters."""

    balance: float = 10000.0
    currency: str = "USD"
    spread_bps: float = 2.0          # basis points
    slippage_bps: float = 1.0        # max slippage applied deterministically
    reject_prob: float = 0.0         # 0 => never randomly rejects (deterministic)
    point: float = 0.0001            # pip-size for FX pairs


class MockDemoAdapter(ExecutionAdapter):
    """In-memory demo broker. Reproducible given the same MockConfig."""

    name = "mock"
    mode = "demo"

    def __init__(self, config: Optional[MockConfig] = None):
        self.cfg = config or MockConfig()
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, OrderStatus] = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_account(self) -> AccountInfo:
        raw = redact(f'{{"broker":"mock","mode":"{self.mode}","balance":{self.cfg.balance}}}')
        return AccountInfo(
            broker=self.name, broker_mode=self.mode,
            balance=self.cfg.balance, currency=self.cfg.currency, raw_redacted=raw,
        )

    def get_prices(self, symbol: str) -> PriceQuote:
        # Deterministic pseudo-midpoint from symbol hash so prices are stable-ish.
        mid = 1.0 + (abs(hash(symbol)) % 1000) / 10000.0
        spread = self.cfg.spread_bps / 10000.0 * mid
        return PriceQuote(
            symbol=symbol, bid=round(mid - spread / 2, 5),
            ask=round(mid + spread / 2, 5), spread=round(spread, 5), timestamp=self._now(),
        )

    def place_demo_order(self, order: DemoOrderRequest) -> OrderStatus:
        if self.mode != "demo":
            return OrderStatus(
                order_id="", status="rejected", rejection_reason="live mode forbidden",
                raw_redacted=redact(f'mode={self.mode}'),
            )
        if order.requested_entry is None:
            return OrderStatus(order_id="", status="rejected",
                               rejection_reason="missing requested_entry")
        spread = self.cfg.spread_bps / 10000.0 * order.requested_entry
        slip = self.cfg.slippage_bps / 10000.0 * order.requested_entry
        # Deterministically fill on the unfavourable side by slippage.
        if order.side == "buy":
            filled = order.requested_entry + spread / 2 + slip
        else:
            filled = order.requested_entry - spread / 2 - slip
        oid = f"MOCK-{uuid.uuid4().hex[:10].upper()}"
        status = OrderStatus(
            order_id=oid, status="filled", filled_entry=round(filled, 5),
            spread_at_entry=round(spread, 5), slippage=round(slip, 5),
            raw_redacted=redact(f'{{"oid":"{oid}","mode":"demo"}}'),
        )
        self._orders[oid] = status
        self._positions[oid] = Position(
            order_id=oid, symbol=order.symbol, side=order.side, units=order.units,
            open_price=round(filled, 5), stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            raw_redacted=redact(f'{{"oid":"{oid}","mode":"demo"}}'),
        )
        return status

    def close_demo_order(self, order_id: str) -> OrderStatus:
        pos = self._positions.pop(order_id, None)
        st = self._orders.get(order_id)
        if st is None:
            return OrderStatus(order_id=order_id, status="rejected",
                               rejection_reason="unknown order_id")
        new_st = OrderStatus(
            order_id=order_id, status="closed", filled_entry=st.filled_entry,
            spread_at_entry=st.spread_at_entry, slippage=st.slippage,
            raw_redacted=redact(f'{{"oid":"{order_id}","mode":"demo"}}'),
        )
        self._orders[order_id] = new_st
        return new_st

    def get_open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_order_status(self, order_id: str) -> OrderStatus:
        st = self._orders.get(order_id)
        if st is None:
            return OrderStatus(order_id=order_id, status="rejected",
                               rejection_reason="unknown order_id")
        return st
