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
    """Raise ValueError unless trade_mode is exactly ACCOUNT_TRADE_MODE_DEMO (0).

    The hard invariant is demo-only (trade_mode == 0). Contest (1) and REAL (2)
    and any unknown value are all refused — never place an order on a non-demo
    account.
    """
    mode = int(trade_mode)
    if mode != ACCOUNT_TRADE_MODE_DEMO:
        raise ValueError(
            f"non-demo trade_mode={mode} (required 0=DEMO) — demo bridge refuses")


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

# ---- Broker-specific zero-spread policy (MetaQuotes-Demo) ----
# Upstream MetaQuotes-Demo behaviour (confirmed by Kade's PC diagnostics):
#   * symbol_info bid/ask can be EQUAL (zero spread) on most live EURUSD ticks
#   * occasional ticks carry a 1-2 point spread
#   * timestamps AND prices continue updating (feed is live)
# The preflight must therefore ALLOW a fresh bid==ask tick ONLY for an
# explicitly whitelisted demo broker (e.g. "MetaQuotes-Demo"). For any
# non-demo or unknown broker, bid==ask is treated as malformed and BLOCKED.
# This is NEVER applied silently to real/live brokers.
ZERO_SPREAD_DEMO_BROKERS = frozenset({"MetaQuotes-Demo"})


class ZeroSpreadPolicy:
    """Controls whether a fresh bid==ask (zero-spread) tick is permitted.

    - ``zero_spread_demo_brokers``: demo-broker identifiers for which a fresh
      bid==ask tick is allowed (with a ``zero_spread_tick`` warning). The
      identifier is matched case-insensitively against the broker's
      ``company`` or ``server`` name reported by the bridge.
    - For any broker NOT in this set (including all real/live brokers and any
      unknown/empty identity), a bid==ask tick is rejected as malformed.
    """

    def __init__(self, brokers=frozenset(ZERO_SPREAD_DEMO_BROKERS)):
        self.zero_spread_demo_brokers = frozenset(b.lower() for b in brokers)

    def allows_zero_spread(self, broker: str) -> bool:
        if not broker:
            return False
        return broker.lower() in self.zero_spread_demo_brokers

    def allows_identity(self, company: str, server: str) -> bool:
        """True if EITHER the broker's company OR server name is whitelisted.

        The upstream demo broker reports ``company='MetaQuotes Ltd.'`` (vendor)
        and ``server='MetaQuotes-Demo'`` (the demo server). The zero-spread
        exception must key off the ``server`` value, so we test both fields.
        """
        return self.allows_zero_spread(company) or self.allows_zero_spread(server)


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
                  now: Optional[datetime] = None) -> Optional[tuple]:
    """Validate a single broker tick.

    Returns None when the tick passes the GLOBAL checks, or a 2-tuple
    ``(reason, zero_spread)`` when it fails, where ``zero_spread`` is True
    iff the only problem is ``bid == ask`` (a zero-spread tick). The caller
    (check_symbol_tradable) decides whether a zero-spread tick is permitted
    for the specific broker.

    GLOBAL checks (apply to EVERY broker, demo or real):
      * bid/ask numeric and finite
      * bid > 0 and ask > 0
      * bid <= ask                       (bid == ask is a zero-spread tick)
      * timestamp present and parseable
      * tick age <= max_age_seconds      (staleness is the primary liveness gate)
    """
    try:
        b = float(bid); a = float(ask)
    except (TypeError, ValueError):
        return ("tick bid/ask not numeric", False)
    if not (math.isfinite(b) and math.isfinite(a)):
        return ("tick bid/ask not finite", False)
    if b <= 0 or a <= 0:
        return ("tick bid/ask not positive", False)
    if b > a:
        # Malformed: a bid above the ask can never be valid. Always reject.
        return (f"tick bid > ask (malformed): {b} > {a}", False)
    age = tick_age_seconds(timestamp, now=now)
    if age is None:
        return ("tick timestamp missing/unparseable", False)
    if age > float(max_age_seconds):
        return (f"tick stale: age {age:.0f}s > {max_age_seconds:.0f}s max", False)
    if b == a:
        # Zero-spread tick: passes GLOBAL checks but needs a broker policy.
        return (f"tick bid == ask (zero-spread): {b}", True)
    return None


def check_symbol_tradable(
    tick1_bid, tick1_ask, tick1_ts: Optional[str],
    tick2_bid, tick2_ask, tick2_ts: Optional[str],
    session_open: Optional[bool] = None,
    max_tick_age_seconds: float = DEFAULT_MAX_TICK_AGE_SECONDS,
    now: Optional[datetime] = None,
    broker: str = "unknown",
    broker_mode: str = "demo",
    broker_company: str = "",
    broker_server: str = "",
    zero_spread_policy: Optional[ZeroSpreadPolicy] = None,
) -> tuple[bool, Optional[str], list]:
    """Tick-evidence market-open preflight (broker-aware zero-spread policy).

    Returns (tradable, reject_reason, warnings).

    REJECT (tradable=False) when ANY tick fails a GLOBAL check:
      * bid/ask not numeric / not finite / not positive
      * bid > ask                                    -> MALFORMED, always blocked
      * missing / unparseable / stale timestamp        -> FEED DEAD, blocked
      * bid == ask (zero-spread) for a broker that is NOT whitelisted for it
        -> blocked unless the broker is an explicitly configured demo broker

    ALLOW a zero-spread (bid == ask) tick ONLY when:
      * it is fresh (timestamp present, age within threshold), AND
      * the broker identity matches an explicitly configured demo broker
        (default whitelist: "MetaQuotes-Demo"), AND broker_mode == "demo".
      In that case the tick is allowed and a ``zero_spread_tick`` WARNING is
      emitted. Real/live brokers and any unknown broker are NEVER granted this
      exception — the zero-spread policy is demo-only and explicit.

    ADVISORY ONLY (never a reject) — surfaced in ``warnings``:
      * ``session_open is False`` — diagnostic metadata only.
      * Inside the FX weekend window — a fresh valid tick still proceeds.

    The broker order attempt (TRADE_RETCODE_MARKET_CLOSED = 10018) remains the
    authoritative closure signal. Two identical-but-fresh ticks are allowed;
    the price is NOT required to change between samples. Fresh timestamp is the
    primary liveness evidence.
    """
    now = now or datetime.now(timezone.utc)
    warnings: list = []
    policy = zero_spread_policy or ZeroSpreadPolicy()
    is_demo = str(broker_mode).lower() == "demo"
    zero_spread_allowed = policy.allows_identity(broker_company, broker_server)

    for label, (tb, ta, tts) in (
        ("first", (tick1_bid, tick1_ask, tick1_ts)),
        ("second", (tick2_bid, tick2_ask, tick2_ts)),
    ):
        res = validate_tick(tb, ta, tts,
                            max_age_seconds=max_tick_age_seconds, now=now)
        if res is None:
            continue  # globally valid (incl. positive spread)
        reason, zero_spread = res
        if zero_spread:
            # Zero-spread tick: allowed ONLY for an explicitly configured demo
            # broker (never real/unknown).
            if is_demo and zero_spread_allowed:
                warnings.append(
                    f"zero_spread_tick: {label} tick bid==ask ({tb}) on demo "
                    f"broker {broker!r} (company={broker_company!r}, "
                    f"server={broker_server!r}) — allowed per explicit "
                    f"zero-spread policy")
                continue
            return False, (f"{label} tick zero-spread (bid==ask) rejected: "
                           f"broker {broker!r} (company={broker_company!r}, "
                           f"server={broker_server!r}, mode={broker_mode}) is "
                           f"not explicitly whitelisted for zero-spread ticks"), warnings
        return False, f"{label} tick invalid: {reason}", warnings

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
