"""ExecutionAdapter interface + shared dataclasses for the demo bridge."""
from __future__ import annotations

import re
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# Anything that looks like a credential is replaced before logging / storing.
SENSITIVE_KEYS = frozenset({
    "token", "secret", "apikey", "api_key", "password", "passwd",
    "authorization", "bearer", "key", "auth",
})
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret|token|password|passwd|authorization|auth|key)"
    r"(\s*[:=]\s*['\"]?)[^\s,'\"&}]{6,}"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;\"']+")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def redact_obj(obj):
    """Recursively redact values whose field names identify credentials."""
    try:
        if isinstance(obj, dict):
            return {
                key: ("[REDACTED]" if str(key).lower() in SENSITIVE_KEYS
                      else redact_obj(value))
                for key, value in obj.items()
            }
        if isinstance(obj, list):
            return [redact_obj(value) for value in obj]
        if isinstance(obj, tuple):
            return tuple(redact_obj(value) for value in obj)
        return obj
    except Exception:
        try:
            return str(obj)
        except Exception:
            return "[UNPRINTABLE]"


def _redact_url(match: re.Match) -> str:
    try:
        parts = urlsplit(match.group(0))
        hostname = parts.hostname or ""
        if parts.port is not None:
            hostname += f":{parts.port}"
        query = "&".join(
            f"{key}={'[REDACTED]' if key.lower() in SENSITIVE_KEYS else value}"
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        )
        return urlunsplit((parts.scheme, hostname, parts.path, query, parts.fragment))
    except Exception:
        return "[REDACTED URL]"


def redact(text: str) -> str:
    """Redact credentials in structured JSON and free-form log strings."""
    if not text:
        return ""
    try:
        if not isinstance(text, str):
            transformed = redact_obj(text)
            return str(transformed)
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(redact_obj(parsed))
        result = _URL_RE.sub(_redact_url, text)
        result = _BEARER_RE.sub("Bearer [REDACTED]", result)
        return _SECRET_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", result)
    except Exception:
        try:
            return str(text)
        except Exception:
            return "[UNPRINTABLE]"


@dataclass
class DemoOrderRequest:
    """A forward-test order with mandatory SL, TP, and signal lineage."""

    symbol: str
    side: str                       # 'buy' | 'sell'
    units: float
    stop_loss: float
    take_profit: float
    signal_id: int
    signal_timestamp: str
    execution_class: str
    requested_entry: Optional[float] = None


@dataclass
class AccountInfo:
    broker: str
    broker_mode: str                # always 'demo'
    balance: float
    currency: str = "USD"
    # Broker identity (company/server) reported by the bridge's account_info().
    # Used by the preflight to apply broker-specific policies (e.g. the
    # MetaQuotes-Demo zero-spread exception). Empty when unknown.
    company: str = ""
    server: str = ""
    raw_redacted: str = ""


@dataclass
class PriceQuote:
    symbol: str
    bid: float
    ask: float
    spread: float
    timestamp: str = ""
    # Broker session signal from symbol_info().session_open, if the Python API
    # exposes it. None means "unknown" — the preflight must fall back to tick
    # evidence and must NOT treat trade_mode as a market-open signal.
    session_open: Optional[bool] = None


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
    status: str                     # pending|filled|placed|rejected|closed
    filled_entry: Optional[float] = None
    rejection_reason: Optional[str] = None
    spread_at_entry: Optional[float] = None
    slippage: Optional[float] = None
    deal_id: Optional[str] = None
    position_id: Optional[str] = None
    type_filling_used: Optional[str] = None
    partial: bool = False
    filled_units: Optional[float] = None
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
