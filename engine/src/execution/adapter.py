"""ExecutionAdapter interface + shared dataclasses for the demo bridge."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# Anything that looks like a credential is replaced before logging / storing.
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|secret|token|password|passwd|bearer)\s*[:=]\s*['\"]?[\w\-./+]{6,}",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Redact credential-like values from a string (logs + raw responses)."""
    if not text:
        return ""
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)


@dataclass
class DemoOrderRequest:
    """A forward-test order derived from a paper signal. SL+TP are mandatory."""

    symbol: str
    side: str                       # 'buy' | 'sell'
    units: float
    stop_loss: float
    take_profit: float
    signal_id: Optional[int] = None
    requested_entry: Optional[float] = None


@dataclass
class AccountInfo:
    broker: str
    broker_mode: str                # always 'demo'
    balance: float
    currency: str = "USD"
    raw_redacted: str = ""


@dataclass
class PriceQuote:
    symbol: str
    bid: float
    ask: float
    spread: float
    timestamp: str = ""


@dataclass
class Position:
    order_id: str
    symbol: str
    side: str
    units: float
    open_price: float
    stop_loss: float
    take_profit: float
    raw_redacted: str = ""


@dataclass
class OrderStatus:
    order_id: str
    status: str                     # pending|filled|rejected|closed
    filled_entry: Optional[float] = None
    rejection_reason: Optional[str] = None
    spread_at_entry: Optional[float] = None
    slippage: Optional[float] = None
    raw_redacted: str = ""


@dataclass
class BrokerCapability:
    """Readiness report for one broker demo adapter (no secret values)."""
    broker: str
    broker_mode: str                # always 'demo'
    credentials_present: bool       # true/false only — never the value
    account_reachable: bool
    account_currency: Optional[str] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    trading_enabled: bool = False
    market_open: Optional[bool] = None
    last_checked_at: str = ""
    last_error_redacted: str = ""


class ExecutionAdapter(ABC):
    """Broker-agnostic demo execution surface. Demo/paper only."""

    name: str = "abstract"
    mode: str = "demo"

    @abstractmethod
    def get_account(self) -> AccountInfo:
        ...

    @abstractmethod
    def get_prices(self, symbol: str) -> PriceQuote:
        ...

    @abstractmethod
    def place_demo_order(self, order: DemoOrderRequest) -> OrderStatus:
        """Submit a demo order. Returns a status (may be rejected)."""
        ...

    @abstractmethod
    def close_demo_order(self, order_id: str) -> OrderStatus:
        ...

    @abstractmethod
    def get_open_positions(self) -> list[Position]:
        ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        ...
