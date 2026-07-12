"""Pure, dependency-free validation shared by the Remote MT5 Bridge (PC side)
and the Aether Forex Lab VPS execution engine.

Kept free of FastAPI / MetaTrader5 imports so it can be imported in unit tests
and on either host without heavy dependencies.
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


# ---- MetaTrader5 volume normalization ----
# Aether emits signals in "units" where the bridge converts to MT5 lots using
# units / 10000.0 (observed: signal #5 with units=2000 -> 0.2 lots). Values in
# (0, 1) are treated as already being lots. Observed failure: signal #5 (units=2000)
# was rejected by MT5 with TRADE_RETCODE_INVALID_VOLUME (10014). We now (a) normalize
# robustly, (b) snap to the symbol's volume_step, (c) reject rather than inflate
# below volume_min, and (d) run mt5.order_check BEFORE order_send so an invalid
# volume is rejected with debug-safe introspection instead of a raw retcode 10014.
UNITS_PER_LOT = 10000.0


class VolumeInfo:
    """Symbol volume constraints used to normalize + validate a requested volume."""

    def __init__(self, volume_min: float, volume_step: float, volume_max: float):
        self.volume_min = float(volume_min)
        self.volume_step = float(volume_step)
        self.volume_max = float(volume_max)


def _snap_to_step(value: float, step: float, vmin: float, vmax: float) -> tuple[float, bool]:
    """Snap `value` DOWN to the nearest multiple of `step`, clamp to [vmin, vmax].

    MT5 requires `volume % volume_step == 0` (within float epsilon). Rounding DOWN
    avoids overshooting volume_max. Returns ``(snapped, too_small)`` where
    ``too_small`` is True when the snapped value falls below volume_min — in that
    case the request cannot be honored without inflating risk, so the caller must
    reject rather than silently bump up to volume_min.
    """
    if step <= 0:
        clamped = max(vmin, min(vmax, value))
        return clamped, clamped < vmin
    snapped = math.floor(value / step) * step
    snapped = round(snapped, 10)  # kill float drift
    if snapped < vmin:
        return snapped, True
    return min(snapped, vmax), False


def normalize_volume(units: float, info: VolumeInfo) -> dict:
    """Convert a requested `units` value into an MT5 lot volume.

    Semantics:
      * units >= 1     -> forex units; lots = units / 100000.0
      * 0 < units < 1  -> already expressed in lots
      * units <= 0     -> invalid (rejected)

    The computed lots are snapped to ``info.volume_step`` and clamped to
    ``[volume_min, volume_max]``. Returns a dict with the resolved values and a
    ``valid`` flag so callers can reject before touching the broker.
    """
    requested_units = float(units)
    if requested_units <= 0:
        return {
            "requested_units": requested_units,
            "calculated_lots": 0.0,
            "normalized_lots": 0.0,
            "volume_min": info.volume_min,
            "volume_step": info.volume_step,
            "volume_max": info.volume_max,
            "valid": False,
            "reason": "units must be positive",
        }
    if requested_units >= 1.0:
        calculated = requested_units / UNITS_PER_LOT
    else:
        calculated = requested_units  # already in lots
    normalized, too_small = _snap_to_step(
        calculated, info.volume_step, info.volume_min, info.volume_max)
    valid = (not too_small) and normalized >= info.volume_min and normalized <= info.volume_max and normalized > 0
    reason = None
    if not valid:
        reason = (
            f"normalized volume {normalized:g} outside [{info.volume_min:g}, {info.volume_max:g}] "
            f"(step {info.volume_step:g})"
        )
    return {
        "requested_units": requested_units,
        "calculated_lots": calculated,
        "normalized_lots": normalized,
        "volume_min": info.volume_min,
        "volume_step": info.volume_step,
        "volume_max": info.volume_max,
        "valid": valid,
        "reason": reason,
    }


def execute_demo_order(mt5, request: dict, symbol_mapped: str,
                       broker_mode: str = "demo") -> dict:
    """Send a demo order after running mt5.order_check.

    `mt5` is the imported MetaTrader5 module (injected so this stays testable
    without the SDK). `request` is the order dict (already containing a
    normalized `volume`). Returns a JSON-serializable result dict. On any
    rejection, includes debug-safe volume fields and never leaks secrets.

    No live trading path exists: if `broker_mode` is not 'demo' the order is
    refused outright.
    """
    if broker_mode != "demo":
        return {
            "status": "refused",
            "rejection_reason": "live trading is not permitted via the demo bridge",
            "broker_mode": broker_mode,
        }

    vol = request.get("volume", 0.0)
    try:
        info = mt5.symbol_info(symbol_mapped)
    except Exception:
        info = None
    volume_min = float(getattr(info, "volume_min", 0.0)) if info else 0.0
    volume_step = float(getattr(info, "volume_step", 0.0)) if info else 0.0
    volume_max = float(getattr(info, "volume_max", 0.0)) if info else 0.0

    # --- pre-send validation: order_check (cheap, no fill) ---
    check = mt5.order_check(request)
    if check is None:
        return {
            "status": "rejected",
            "rejection_reason": "order_check returned None — broker rejected pre-check",
            "broker_mode": broker_mode,
            "request_volume": vol,
            "request_symbol": symbol_mapped,
            "request_side": request.get("type"),
            "volume_min": volume_min,
            "volume_step": volume_step,
            "volume_max": volume_max,
        }
    if getattr(check, "retcode", 1) != mt5.TRADE_RETCODE_DONE:
        return {
            "status": "rejected",
            "rejection_reason": (
                f"order_check failed: retcode {getattr(check, 'retcode', '?')} "
                f"({getattr(check, 'comment', '') or ''})"
            ),
            "order_check_retcode": getattr(check, "retcode", None),
            "order_check_comment": getattr(check, "comment", "") or "",
            "type_filling_used": request.get("type_filling"),
            "requested_units": request.get("requested_units"),
            "calculated_lots": request.get("calculated_lots"),
            "normalized_lots": vol,
            "volume_min": volume_min,
            "volume_step": volume_step,
            "volume_max": volume_max,
            "broker_mode": broker_mode,
        }

    # --- live send ---
    result = mt5.order_send(request)
    if getattr(result, "retcode", 1) != mt5.TRADE_RETCODE_DONE:
        return {
            "status": "rejected",
            "rejection_reason": f"mt5 retcode {getattr(result, 'retcode', '?')}",
            "mt5_retcode": getattr(result, "retcode", None),
            "mt5_comment": getattr(result, "comment", "") or "",
            "request_volume": vol,
            "request_symbol": symbol_mapped,
            "request_side": request.get("type"),
            "broker_mode": broker_mode,
            "order_check_retcode": getattr(check, "retcode", None),
            "order_check_comment": getattr(check, "comment", "") or "",
            "type_filling_used": request.get("type_filling"),
            "requested_units": request.get("requested_units"),
            "calculated_lots": request.get("calculated_lots"),
            "normalized_lots": vol,
            "volume_min": volume_min,
            "volume_step": volume_step,
            "volume_max": volume_max,
        }
    return {
        "status": "filled",
        "order_id": str(getattr(result, "order", "")),
        "filled_entry": float(getattr(result, "price", 0.0)),
        "spread_at_entry": request.get("spread_at_entry", 0.0),
        "slippage": 0.0,
        "broker_mode": broker_mode,
        "type_filling_used": request.get("type_filling"),
        "volume": vol,
    }
