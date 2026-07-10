"""Adapter factory for the demo execution bridge.

Selection rules (fail-loud, safe-by-default):
  * 'mock' is always available and is the DEFAULT.
  * 'deriv_mt5' / 'oanda_practice' are returned ONLY if their credentials are
    present; otherwise the factory raises so the bridge stays disabled and the
    caller can fall back to 'mock'.
  * Anything other than a demo adapter name is rejected.
"""
from __future__ import annotations

import os
from typing import Optional

from .adapter import ExecutionAdapter
from .mock_adapter import MockDemoAdapter
from .guards import MAX_OPEN_DEMO_TRADES_DEFAULT


def available_adapters() -> dict:
    """Report which adapters can be built right now (creds present?)."""
    out = {"mock": True}
    out["deriv_mt5"] = all(
        os.environ.get(f"DERIV_MT5_{k}") for k in ("LOGIN", "PASSWORD", "SERVER")
    )
    out["oanda_practice"] = bool(
        os.environ.get("OANDA_PRACTICE_API_KEY") and os.environ.get("OANDA_PRACTICE_ACCOUNT")
    )
    return out


def list_adapters() -> dict:
    return available_adapters()


def build_adapter(name: Optional[str] = None, *, fail_loud: bool = True) -> ExecutionAdapter:
    """Return an adapter by name. Default 'mock'.

    fail_loud=True: raise if a real adapter is requested but creds are missing.
    fail_loud=False: silently fall back to 'mock' in that case.
    """
    name = (name or "mock").lower()
    if name == "mock":
        return MockDemoAdapter()

    if name == "deriv_mt5":
        if not available_adapters()["deriv_mt5"]:
            if fail_loud:
                raise RuntimeError(
                    "deriv_mt5 unavailable: missing DERIV_MT5_LOGIN/PASSWORD/SERVER. "
                    "Use 'mock' or provide demo credentials."
                )
            return MockDemoAdapter()
        from .deriv_mt5 import DerivMT5DemoAdapter

        return DerivMT5DemoAdapter()

    if name == "oanda_practice":
        if not available_adapters()["oanda_practice"]:
            if fail_loud:
                raise RuntimeError(
                    "oanda_practice unavailable: missing OANDA_PRACTICE_API_KEY/ACCOUNT. "
                    "Use 'mock' or provide practice credentials."
                )
            return MockDemoAdapter()
        from .oanda_practice import OandaPracticeAdapter

        return OandaPracticeAdapter()

    raise ValueError(f"unknown adapter {name!r}; allowed: mock, deriv_mt5, oanda_practice")
