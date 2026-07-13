"""Pure, dependency-free validation shared by the Remote MT5 Bridge (PC side)
and the Aether Forex Lab VPS execution engine.

Kept free of FastAPI / MetaTrader5 imports so it can be imported in unit tests
and on either host without heavy dependencies.

NOTE: this file is intentionally duplicated in remote-mt5-bridge/ so each deploy
target is self-contained (the PC bridge ships without the engine).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

# ---- MetaTrader5 ACCOUNT_TRADE_MODE enum (observed SDK values) ----
#   0 = DEMO, 1 = CONTEST, 2 = REAL
# CRITICAL: trade_mode == 0 is DEMO, NOT live. Only REAL (2) must be refused.
ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

# Conservative default max age for a paper signal before it may be executed as a
# real demo order (minutes). A stale signal's SL/TP geometry no longer matches
# the live market, so execution must be refused.
DEFAULT_SIGNAL_MAX_AGE_MINUTES = 30


def check_demo_trade_mode(trade_mode: int) -> None:
    """Raise ValueError unless trade_mode indicates a non-live (demo/contest) account.

    Only REAL (2) is refused. trade_mode == 0 (DEMO) and 1 (CONTEST) are accepted.
    """
    mode = int(trade_mode)
    if mode == ACCOUNT_TRADE_MODE_REAL:
        raise ValueError("LIVE account detected — demo bridge refuses")
    # 0 (demo) and 1 (contest) are both acceptable for the demo bridge.


def is_live_trade_mode(trade_mode: int) -> bool:
    return int(trade_mode) == ACCOUNT_TRADE_MODE_REAL


def validate_price_geometry(
    side: str,
    entry: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
) -> Optional[str]:
    """Return a rejection reason if SL/TP do not bracket `entry` on the correct side.

    buy : stop_loss < entry < take_profit
    sell : take_profit < entry < stop_loss

    Returns None when the geometry is valid. `entry` is the projected fill price
    (current ask for a buy, current bid for a sell).
    """
    if stop_loss is None or take_profit is None:
        return "stop_loss and take_profit are mandatory"
    if side == "buy":
        if not (stop_loss < entry < take_profit):
            return (
                f"invalid buy geometry: need SL({stop_loss}) < entry({entry}) < TP({take_profit})"
            )
    elif side == "sell":
        if not (take_profit < entry < stop_loss):
            return (
                f"invalid sell geometry: need TP({take_profit}) < entry({entry}) < SL({stop_loss})"
            )
    else:
        return f"unknown side {side!r}"
    return None


def signal_age_minutes(
    timestamp: Optional[str], now: Optional[datetime] = None
) -> Optional[float]:
    """Age of a signal timestamp in minutes, or None if unparseable/missing."""
    if not timestamp:
        return None
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() / 60.0


def is_stale_signal(
    timestamp: Optional[str],
    max_age_minutes: float,
    execution_class: str = "paper",
    now: Optional[datetime] = None,
) -> bool:
    """True when a signal is too old to execute as a real demo order.

    Signals explicitly marked ``backtest_only`` or ``paper_only`` are exempt: they
    are never forwarded to a broker, so staleness is irrelevant (the execution
    path rejects them for a different reason).
    """
    if execution_class in ("backtest_only", "paper_only"):
        return False
    age = signal_age_minutes(timestamp, now=now)
    if age is None:
        return False
    return age > float(max_age_minutes)


# ---- Market-session preflight (revised, tick-evidence based) ----
# Authoritative source of "is the market open" is the BROKER:
#   * a FRESH, VALID tick is sufficient evidence the market is live, OR
#   * TRADE_RETCODE_MARKET_CLOSED (10018) returned on the order attempt itself.
# Design rules (per Kade):
#   * A fresh tick (finite, positive, bid<ask, recent timestamp) is enough to
#     proceed. We do NOT require the price to change between two samples — two
#     identical fresh ticks are NOT proof the market is closed.
#   * session_open (from symbol_info().session_open, IF present AND a real bool)
#     is OPTIONAL DIAGNOSTIC METADATA ONLY. It never causes a reject. NOTE: in the
#     real MetaTrader5 Python SDK, symbol_info().session_open is a PRICE field (or
#     0.0), NOT a market-open boolean — session state requires
#     mt5.symbol_info_session_trade(). The bridge therefore returns null unless it
#     is actually a bool, and the preflight never blocks on it.
#   * The weekly calendar (FX spot Sun 22:00 -> Fri 22:00 UTC) is purely ADVISORY:
#     a fresh valid tick is NEVER rejected for being inside the weekend window.
#   * trade_mode is NOT a market-open signal (it reports the account/symbol
#     trading mode/status only). No hard-coded daily closure is used.
# Keep in sync with remote-mt5-bridge/bridge_validation.py (intentional duplicate).

# Advisory-only weekly window. Used for a WARNING, never a reject.
_ADVISORY_FX_WEEK_OPEN_WEEKDAY = 6   # Sunday
_ADVISORY_FX_WEEK_OPEN_HOUR = 22     # 22:00 UTC
_ADVISORY_FX_WEEK_CLOSE_WEEKDAY = 4  # Friday
_ADVISORY_FX_WEEK_CLOSE_HOUR = 22    # 22:00 UTC

# How stale a tick may be before we consider the feed dead (seconds).
DEFAULT_MAX_TICK_AGE_SECONDS = 30.0


def _advisory_weekend_closed(now: Optional[datetime] = None) -> bool:
    """Advisory only: True during the widely-known FX weekend close
    (Friday 22:00 UTC -> Sunday 22:00 UTC). Returns False otherwise. This is
    NEVER used to reject an otherwise fresh, valid tick.
    """
    now = now or datetime.now(timezone.utc)
    wd = now.weekday()  # Monday=0 .. Sunday=6
    h = now.hour
    if wd == _ADVISORY_FX_WEEK_CLOSE_WEEKDAY and h >= _ADVISORY_FX_WEEK_CLOSE_HOUR:
        return True
    if wd == 5:  # Saturday
        return True
    if wd == _ADVISORY_FX_WEEK_OPEN_WEEKDAY and h < _ADVISORY_FX_WEEK_OPEN_HOUR:
        return True
    return False


def tick_age_seconds(timestamp: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Age of a tick timestamp in seconds, or None if unparseable/missing."""
    if not timestamp:
        return None
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds()


def validate_tick(bid, ask, timestamp: Optional[str],
                  max_age_seconds: float = DEFAULT_MAX_TICK_AGE_SECONDS,
                  now: Optional[datetime] = None) -> Optional[str]:
    """Validate a single broker tick. Return a rejection reason string, or None
    if the tick is acceptable (finite, positive, bid<ask, recent timestamp).
    A fresh valid tick is sufficient evidence of an open market.
    """
    try:
        b = float(bid); a = float(ask)
    except (TypeError, ValueError):
        return "tick bid/ask not numeric"
    if not (math.isfinite(b) and math.isfinite(a)):
        return "tick bid/ask not finite"
    if b <= 0 or a <= 0:
        return "tick bid/ask not positive"
    if b >= a:
        return f"tick bid >= ask ({b} >= {a})"
    age = tick_age_seconds(timestamp, now=now)
    if age is None:
        return "tick timestamp missing/unparseable"
    if age > float(max_age_seconds):
        return f"tick stale: age {age:.0f}s > {max_age_seconds:.0f}s max"
    return None


def check_symbol_tradable(
    tick1_bid, tick1_ask, tick1_ts: Optional[str],
    tick2_bid, tick2_ask, tick2_ts: Optional[str],
    session_open: Optional[bool] = None,
    max_tick_age_seconds: float = DEFAULT_MAX_TICK_AGE_SECONDS,
    now: Optional[datetime] = None,
) -> tuple[bool, Optional[str], list]:
    """Tick-evidence market-open preflight.

    Returns (tradable, reject_reason, warnings).

    REJECT (tradable=False) ONLY when a tick is invalid or stale:
      * bid/ask not numeric / not finite / not positive
      * bid >= ask
      * missing or unparseable timestamp
      * tick age beyond ``max_tick_age_seconds`` (default 30s)

    ADVISORY ONLY (never a reject) — surfaced in ``warnings``:
      * ``session_open is False`` — diagnostic metadata only; the real MT5
        symbol_info() does not expose this field, so it is not a trusted gate.
      * Inside the FX weekend window — a fresh valid tick still proceeds.

    The broker order attempt (TRADE_RETCODE_MARKET_CLOSED = 10018) remains the
    authoritative closure signal. Two identical-but-fresh ticks are allowed; the
    price is NOT required to change between samples.
    """
    now = now or datetime.now(timezone.utc)
    warnings: list = []
    r1 = validate_tick(tick1_bid, tick1_ask, tick1_ts,
                       max_age_seconds=max_tick_age_seconds, now=now)
    if r1:
        return False, f"first tick invalid: {r1}", warnings
    r2 = validate_tick(tick2_bid, tick2_ask, tick2_ts,
                       max_age_seconds=max_tick_age_seconds, now=now)
    if r2:
        return False, f"second tick invalid: {r2}", warnings
    # ---- advisory-only diagnostics (never reject) ----
    if session_open is False:
        warnings.append(
            "broker session_open=False reported (diagnostic only; not a hard "
            "gate — symbol_info().session_open is a price field, not a market "
            "open/close boolean in MT5 Python)")
    if _advisory_weekend_closed(now=now):
        warnings.append(
            "advisory: within FX weekend close window (Fri22:00 -> Sun22:00 UTC)")
    return True, None, warnings
