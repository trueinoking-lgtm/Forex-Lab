"""Adapter factory + execution-mode resolution for the demo execution bridge.

Selection rules (fail-loud, safe-by-default):
  * 'mock' is always available and is the DEFAULT (deterministic, no network).
  * 'oanda_practice' / 'mt5_demo' are returned ONLY if their credentials are
    present; otherwise the factory raises so the bridge stays disabled and the
    caller can fall back to 'mock'.
  * 'deriv_mt5' is accepted as an alias of 'mt5_demo' for backward compatibility.
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
    out["oanda_practice"] = bool(
        os.environ.get("OANDA_PRACTICE_API_KEY") and os.environ.get("OANDA_PRACTICE_ACCOUNT")
    )
    out["mt5_demo"] = all(os.environ.get(f"MT5_{k}") for k in ("LOGIN", "PASSWORD", "SERVER"))
    return out


def list_adapters() -> dict:
    return available_adapters()


def broker_names() -> list[str]:
    return ["mock", "oanda_practice", "mt5_demo"]


def build_adapter(name: Optional[str] = None, *, fail_loud: bool = True) -> ExecutionAdapter:
    """Return an adapter by name. Default 'mock'."""
    name = (name or "mock").lower()
    if name == "mock":
        return MockDemoAdapter()

    if name in ("mt5_demo", "deriv_mt5"):
        if not available_adapters()["mt5_demo"]:
            if fail_loud:
                raise RuntimeError(
                    "mt5_demo unavailable: missing MT5_LOGIN/PASSWORD/SERVER or terminal. "
                    "Use 'mock' or provide demo credentials."
                )
            return MockDemoAdapter()
        from .mt5_demo import MT5DemoAdapter
        return MT5DemoAdapter()

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

    raise ValueError(f"unknown adapter {name!r}; allowed: mock, oanda_practice, mt5_demo")


# ===== Execution modes =====
# observe_only (default) | dry_run | single_broker_demo | mirror_demo
def execution_mode() -> str:
    m = os.environ.get("BROKER_EXECUTION_MODE", "observe_only").lower()
    if m not in ("observe_only", "dry_run", "single_broker_demo", "mirror_demo"):
        return "observe_only"
    return m


def primary_demo_broker() -> str:
    b = os.environ.get("PRIMARY_DEMO_BROKER", "oanda_practice").lower()
    return b if b in ("oanda_practice", "mt5_demo") else "oanda_practice"


def mirror_demo_enabled() -> bool:
    return os.environ.get("MIRROR_DEMO_ENABLED", "false").lower() in ("1", "true", "yes")


def dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").lower() not in ("0", "false", "no")


def demo_autotrade_enabled() -> bool:
    return os.environ.get("DEMO_AUTOTRADE_ENABLED", "false").lower() in ("1", "true", "yes")


def can_place_real_demo() -> bool:
    """True only when the system is allowed to place a real demo broker order."""
    return (execution_mode() in ("single_broker_demo", "mirror_demo")
            and demo_autotrade_enabled()
            and not dry_run())
