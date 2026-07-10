"""Demo execution bridge for Aether Forex Lab — PAPER forward-testing only.

SAFETY MODEL (do not weaken):
  * This module NEVER places a real trade. `broker_mode` is hard-locked to 'demo'.
  * `live` / `allow_live_orders` is rejected before any adapter is touched.
  * Broker secrets come ONLY from environment variables; they are never written
    to the database and are redacted from all logs / stored responses.
  * Every demo order MUST pass the deterministic risk engine (src.signals.risk_check)
    AND carry both a stop_loss and a take_profit before it is submitted.
  * No AI-generated trade can bypass these checks: the pre-trade guard runs the
    same deterministic logic for every order regardless of source.
"""
from .adapter import (
    ExecutionAdapter,
    DemoOrderRequest,
    AccountInfo,
    PriceQuote,
    Position,
    OrderStatus,
    redact,
)
from .guards import (
    GuardError,
    run_pretrade_guards,
    MAX_OPEN_DEMO_TRADES_DEFAULT,
)
from .mock_adapter import MockDemoAdapter
from .factory import build_adapter, list_adapters, available_adapters

__all__ = [
    "ExecutionAdapter",
    "DemoOrderRequest",
    "AccountInfo",
    "PriceQuote",
    "Position",
    "OrderStatus",
    "redact",
    "GuardError",
    "run_pretrade_guards",
    "MAX_OPEN_DEMO_TRADES_DEFAULT",
    "MockDemoAdapter",
    "build_adapter",
    "list_adapters",
    "available_adapters",
]
