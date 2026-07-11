"""Deterministic pre-trade guards for the demo execution bridge.

These checks run for EVERY order before any adapter is contacted. They are
source-agnostic: a paper signal and an AI-generated proposal go through the
exact same gate, so no trade can bypass the deterministic risk engine.

Hard rules (fail loud, never silently relax):
  * broker_mode MUST be 'demo' (live rejected).
  * allow_live_orders MUST be False.
  * stop_loss and take_profit are both required and distinct from entry.
  * the deterministic risk engine (src.signals.risk_check) must pass.
  * a paper Signal must exist (paper signal required).
  * open demo orders must not exceed the configured cap (max open).
  * kill switch MUST be off.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..signals import risk_check, PaperSignal
from .adapter import DemoOrderRequest, PriceQuote
from .bridge_validation import (  # shared, zero-dependency validation
    validate_price_geometry, is_stale_signal, DEFAULT_SIGNAL_MAX_AGE_MINUTES,
)

MAX_OPEN_DEMO_TRADES_DEFAULT = 5
DEFAULT_SIGNAL_MAX_AGE_MINUTES = DEFAULT_SIGNAL_MAX_AGE_MINUTES  # re-export for callers


class GuardError(Exception):
    """Raised when a pre-trade guard fails. Carries a machine reason."""


@dataclass
class GuardResult:
    passed: bool
    reasons: list[str]
    risk: Optional[dict] = None


def run_pretrade_guards(
    order: DemoOrderRequest,
    *,
    broker_mode: str,
    allow_live_orders: bool,
    account: float,
    risk_pct: float,
    signal: Optional[PaperSignal],
    open_demo_trades: int,
    max_open_demo_trades: int = MAX_OPEN_DEMO_TRADES_DEFAULT,
    kill_switch: bool = False,
    broker: str = "mock",
    open_demo_trades_by_broker: int = 0,
    max_open_per_broker: Optional[int] = None,
    live_quote: Optional[PriceQuote] = None,
    signal_timestamp: Optional[str] = None,
    execution_class: str = "paper",
    signal_max_age_minutes: float = DEFAULT_SIGNAL_MAX_AGE_MINUTES,
) -> GuardResult:
    """Evaluate all deterministic pre-trade guards. Raises nothing; returns result.

    Callers must treat `passed=False` as a hard reject and NOT submit the order.
    Enforces BOTH a global cap and a per-broker cap.

    When ``live_quote`` (a PriceQuote) is supplied, the SL/TP geometry is checked
    against the ACTUAL current market (stale/invalid SL/TP are rejected). When
    ``signal_timestamp`` is supplied, staleness is enforced against
    ``signal_max_age_minutes`` (exempt for backtest_only/paper_only signals).
    """
    reasons: list[str] = []

    # 1. Never live.
    if broker_mode != "demo":
        reasons.append(f"broker_mode must be 'demo', got {broker_mode!r}")
    if allow_live_orders:
        reasons.append("ALLOW_LIVE_ORDERS is true — demo-only bridge refuses")

    # 2. Kill switch.
    if kill_switch:
        reasons.append("kill switch is engaged — all demo orders refused")

    # 3. Stale signal protection.
    cls = execution_class if execution_class else "paper"
    if signal_timestamp and is_stale_signal(signal_timestamp, signal_max_age_minutes, cls):
        reasons.append(
            f"stale signal: age exceeds {signal_max_age_minutes} min — refuse execution"
        )

    # 4. Stop-loss + take-profit both required and distinct from entry.
    entry = order.requested_entry
    if entry is None:
        reasons.append("missing requested_entry (cannot define SL/TP reference)")
    else:
        if order.stop_loss is None:
            reasons.append("missing stop_loss — every demo order requires a stop-loss")
        elif order.stop_loss == entry:
            reasons.append("stop_loss equals entry — no risk defined")
        if order.take_profit is None:
            reasons.append("missing take_profit — every demo order requires a take-profit")
        elif order.take_profit == entry:
            reasons.append("take_profit equals entry — no target defined")
    # SL/TP must bracket the entry (opposite sides).
    if (
        entry is not None
        and order.stop_loss is not None
        and order.take_profit is not None
        and order.stop_loss == order.take_profit
    ):
        reasons.append("stop_loss and take_profit are identical")

    # 5. Live price-geometry validation (against actual current market when known).
    if (
        entry is not None
        and order.stop_loss is not None
        and order.take_profit is not None
    ):
        # Prefer the real fill price (ask for buy / bid for sell) when a live quote
        # is available; otherwise fall back to the requested entry.
        geom_entry = entry
        if live_quote is not None:
            geom_entry = live_quote.ask if order.side == "buy" else live_quote.bid
        geom_reason = validate_price_geometry(
            order.side, geom_entry, order.stop_loss, order.take_profit
        )
        if geom_reason:
            reasons.append(f"price geometry invalid vs live quote: {geom_reason}")

    # 6. Deterministic risk engine — pass is mandatory.
    risk = None
    if entry is not None and order.stop_loss is not None and order.stop_loss != entry:
        risk = risk_check(account, risk_pct, entry, order.stop_loss)
        if not risk.get("pass"):
            reasons.append(f"risk_check failed: {risk.get('reason')}")
    else:
        reasons.append("risk_check skipped — SL/entry invalid")

    # 7. Paper signal required.
    if signal is None:
        reasons.append("no parent paper Signal — demo order requires a paper signal")

    # 8. Max open demo trades (global + per-broker).
    if open_demo_trades >= max_open_demo_trades:
        reasons.append(
            f"global open demo trades {open_demo_trades} >= cap {max_open_demo_trades}"
        )
    cap_b = max_open_per_broker if max_open_per_broker is not None else max_open_demo_trades
    if open_demo_trades_by_broker >= cap_b:
        reasons.append(
            f"open demo trades for {broker} {open_demo_trades_by_broker} >= per-broker cap {cap_b}"
        )

    return GuardResult(passed=len(reasons) == 0, reasons=reasons, risk=risk)
