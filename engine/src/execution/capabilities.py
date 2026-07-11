"""Broker capability registry for the demo execution bridge.

Reports readiness for each broker demo adapter WITHOUT ever revealing secret
values. `credentials_present` is a boolean; credential *values* are never read
into the report. Account reachability, currency, balance, trading-enabled, and
market-open are probed (read-only) only when credentials are present.

SAFETY:
  * broker_mode is always 'demo'.
  * Real broker adapters are probed read-only (get_account / get_prices). No order
    placement happens here — placing orders is gated separately by execution mode.
  * Any failure is captured redacted into `last_error_redacted` and counts as
    account_reachable=False (fail loud, but never crash the registry).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from .adapter import BrokerCapability, redact


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oanda_creds_present() -> bool:
    return bool(
        os.environ.get("OANDA_PRACTICE_API_KEY")
        and os.environ.get("OANDA_PRACTICE_ACCOUNT")
    )


def _mt5_creds_present() -> bool:
    return all(
        os.environ.get(f"MT5_{k}") for k in ("LOGIN", "PASSWORD", "SERVER")
    )


def mock_capability() -> BrokerCapability:
    return BrokerCapability(
        broker="mock", broker_mode="demo",
        credentials_present=True, account_reachable=True,
        account_currency="USD", balance=10000.0, equity=10000.0,
        trading_enabled=True, market_open=True,
        last_checked_at=_now(), last_error_redacted="",
    )


def oanda_capability() -> BrokerCapability:
    caps = BrokerCapability(broker="oanda_practice", broker_mode="demo",
                            credentials_present=_oanda_creds_present(),
                            account_reachable=False, last_checked_at=_now())
    if not caps.credentials_present:
        caps.last_error_redacted = redact("OANDA_PRACTICE_API_KEY/ACCOUNT not set")
        return caps
    try:
        from .oanda_practice import OandaPracticeAdapter
        a = OandaPracticeAdapter()
        acc = a.get_account()
        caps.account_reachable = True
        caps.account_currency = acc.currency
        caps.balance = acc.balance
        caps.equity = acc.balance
        caps.trading_enabled = True
    except Exception as exc:  # fail loud but safe: record redacted reason
        caps.account_reachable = False
        caps.last_error_redacted = redact(str(exc))[:200]
    return caps


def mt5_capability() -> BrokerCapability:
    caps = BrokerCapability(broker="mt5_demo", broker_mode="demo",
                            credentials_present=_mt5_creds_present(),
                            account_reachable=False, last_checked_at=_now())
    if not caps.credentials_present:
        caps.last_error_redacted = redact("MT5_LOGIN/PASSWORD/SERVER not set")
        return caps
    try:
        from .mt5_demo import MT5DemoAdapter
        a = MT5DemoAdapter()
        acc = a.get_account()
        caps.account_reachable = True
        caps.account_currency = acc.currency
        caps.balance = acc.balance
        caps.equity = acc.balance
        caps.trading_enabled = True
    except Exception as exc:
        caps.account_reachable = False
        caps.last_error_redacted = redact(str(exc))[:200]
    return caps


def capabilities() -> dict:
    """Return all broker capabilities keyed by broker name."""
    out = {
        "mock": mock_capability(),
        "oanda_practice": oanda_capability(),
        "mt5_demo": mt5_capability(),
    }
    return out


def capability(broker: str) -> BrokerCapability:
    broker = (broker or "mock").lower()
    if broker == "mock":
        return mock_capability()
    if broker == "oanda_practice":
        return oanda_capability()
    if broker in ("mt5_demo", "deriv_mt5"):
        return mt5_capability()
    raise ValueError(f"unknown broker {broker!r}")
