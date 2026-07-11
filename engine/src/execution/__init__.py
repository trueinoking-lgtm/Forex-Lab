"""Demo execution bridge for Aether Forex Lab — PAPER / DEMO forward-testing only.

SAFETY MODEL (do not weaken):
  * This module NEVER places a live trade. `broker_mode` is hard-locked to 'demo'.
  * `live` / `allow_live_orders` is rejected before any adapter is touched.
  * Real demo brokers (OANDA Practice, MT5 demo) are contacted ONLY when
    DEMO_AUTOTRADE_ENABLED=true AND DRY_RUN=false AND the execution mode allows it.
    By default the mode is 'observe_only' and NO order is ever placed.
  * Broker secrets come ONLY from environment variables; they are never written
    to the database and are redacted from all logs / stored responses.
  * Every demo order MUST pass the deterministic risk engine (src.signals.risk_check)
    AND carry both a stop_loss and a take_profit before it is submitted.
  * No AI-generated trade can bypass these checks: the pre-trade guard runs the
    same deterministic logic for every order regardless of source.
  * Mock adapter stays deterministic for reproducible tests.
"""
from .adapter import (
    ExecutionAdapter,
    DemoOrderRequest,
    AccountInfo,
    PriceQuote,
    Position,
    OrderStatus,
    BrokerCapability,
    redact,
)
from .guards import (
    GuardError,
    run_pretrade_guards,
    MAX_OPEN_DEMO_TRADES_DEFAULT,
)
from .mock_adapter import MockDemoAdapter
from .factory import (
    build_adapter, list_adapters, available_adapters, broker_names,
    execution_mode, primary_demo_broker, mirror_demo_enabled,
    dry_run, demo_autotrade_enabled, can_place_real_demo,
)
from .capabilities import capabilities, capability
from .oanda_practice import OandaPracticeAdapter, SYMBOL_MAP as OANDA_SYMBOL_MAP
from .mt5_demo import MT5DemoAdapter, DEFAULT_SYMBOL_MAP as MT5_DEFAULT_SYMBOL_MAP

__all__ = [
    "ExecutionAdapter",
    "DemoOrderRequest",
    "AccountInfo",
    "PriceQuote",
    "Position",
    "OrderStatus",
    "BrokerCapability",
    "redact",
    "GuardError",
    "run_pretrade_guards",
    "MAX_OPEN_DEMO_TRADES_DEFAULT",
    "MockDemoAdapter",
    "OandaPracticeAdapter",
    "MT5DemoAdapter",
    "build_adapter",
    "list_adapters",
    "available_adapters",
    "broker_names",
    "capabilities",
    "capability",
    "execution_mode",
    "primary_demo_broker",
    "mirror_demo_enabled",
    "dry_run",
    "demo_autotrade_enabled",
    "can_place_real_demo",
    "OANDA_SYMBOL_MAP",
    "MT5_DEFAULT_SYMBOL_MAP",
]
