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

# Common MetaTrader5 TRADE_RETCODE_* values (used to label reject reasons so the
# caller never has to guess what a raw retcode means).
_TRADE_RETCODE_NAMES = {
    10004: "TRADE_RETCODE_REQUOTE",
    10006: "TRADE_RETCODE_CONNECTION",
    10007: "TRADE_RETCODE_TIMEOUT",
    10008: "TRADE_RETCODE_PLACED",
    10009: "TRADE_RETCODE_DONE",
    10010: "TRADE_RETCODE_DONE_PARTIAL",
    10013: "TRADE_RETCODE_ERROR",
    10014: "TRADE_RETCODE_INVALID_VOLUME",
    10015: "TRADE_RETCODE_INVALID_PRICE",
    10016: "TRADE_RETCODE_INVALID_STOPS",
    10017: "TRADE_RETCODE_TRADE_DISABLED",
    10018: "TRADE_RETCODE_INVALID_FILL",
    10019: "TRADE_RETCODE_TRADE_TIMEOUT",
    10020: "TRADE_RETCODE_TRADE_LIMIT",
    10021: "TRADE_RETCODE_TRADE_HEDGE_PROHIBITED",
    10022: "TRADE_RETCODE_TRADE_FIFO_PROHIBITED",
    10023: "TRADE_RETCODE_TRADE_CONTEXT_BUSY",
    10024: "TRADE_RETCODE_TRADE_EXPERT_DISABLED",
    10025: "TRADE_RETCODE_TRADE_NO_MONEY",
    10026: "TRADE_RETCODE_TRADE_TOO_MANY_REQUESTS",
    10027: "TRADE_RETCODE_TRADE_MODIFY_DENIED",
    10028: "TRADE_RETCODE_TRADE_FILL_RES_ERROR",
    10029: "TRADE_RETCODE_TRADE_ORDER_DIR_PROHIBITED",
    10030: "TRADE_RETCODE_UNSUPPORTED_FILLING_MODE",
}


def trade_retcode_name(mt5, code: int) -> str:
    """Human-readable name for an MT5 trade retcode (with SDK override + fallback)."""
    code = int(code)
    sdk_name = getattr(mt5, f"TRADE_RETCODE_{code}", None) if mt5 is not None else None
    if isinstance(sdk_name, str):
        return sdk_name
    return _TRADE_RETCODE_NAMES.get(code, f"retcode_{code}")


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
# Standard forex convention: 1 lot = 100,000 units of the base currency.
# A signal with units=2000 therefore maps to 0.02 lots.
UNITS_PER_LOT = 100000.0


class VolumeInfo:
    """Symbol volume constraints used to normalize + validate a requested volume."""

    def __init__(self, volume_min: float, volume_step: float, volume_max: float):
        self.volume_min = float(volume_min)
        self.volume_step = float(volume_step)
        self.volume_max = float(volume_max)


def _step_decimals(step: float) -> int:
    """Number of decimal places implied by a volume_step (0.01 -> 2)."""
    if step <= 0:
        return 2
    d = -math.log10(step)
    return max(0, int(round(d)))


def _snap_to_step(value: float, step: float, vmin: float, vmax: float) -> tuple[float, bool]:
    """Snap `value` to a whole multiple of `step`, clamped to [vmin, vmax].

    Built from an INTEGER step count (not repeated float addition) and rounded to
    the step's decimal places so MT5's `volume % volume_step == 0` check passes
    without float-drift rejections (e.g. 0.2 lots vs step 0.01). Returns
    ``(snapped, too_small)`` where ``too_small`` is True when the snapped value
    falls below volume_min — the caller must reject rather than bump to vmin.
    """
    if step <= 0:
        clamped = max(vmin, min(vmax, value))
        return clamped, clamped < vmin
    n = int(round(value / step))
    if n <= 0:
        return 0.0, True
    snapped = round(n * step, _step_decimals(step))
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


def _order_check_passed(result, mt5=None) -> bool:
    """MqlTradeCheckResult.retcode == 0 means the validation passed.

    This is the pre-send order_check; its retcode 0 is NOT the same as an
    order_send trade-server retcode (which uses 10008/10009/10010). So this
    helper must ONLY be used for order_check.
    """
    if result is None:
        return False
    return int(getattr(result, "retcode", 1)) == 0


def _order_send_succeeded(mt5, result) -> bool:
    """order_send uses trade-server retcodes, not 0.

    TRADE_RETCODE_PLACED = 10008, TRADE_RETCODE_DONE = 10009,
    TRADE_RETCODE_DONE_PARTIAL = 10010.
    """
    if result is None:
        return False
    return int(getattr(result, "retcode", 1)) in {
        int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
        int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)),
        int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)),
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

    # --- pre-send validation: find a supported filling mode, then order_check ---
    # Official ENUM_ORDER_TYPE_FILLING: FOK = 0, IOC = 1, RETURN = 2.
    # symbol_info().filling_mode is a SEPARATE flags field (not the order enum):
    #   flag 1 = SYMBOL_FILLING_FOK, flag 2 = SYMBOL_FILLING_IOC.
    # So filling_mode=1 means the symbol permits FOK (NOT RETURN). RETURN has no
    # SYMBOL_FILLING_MODE flag and is not allowed for Market Execution, so we
    # only ever candidate FOK and IOC (derived from the flags), trying each via
    # order_check and using the first the broker accepts.
    fm = int(getattr(info, "filling_mode", 0) or 0)
    candidate_modes = []
    if fm == 0:
        # Unknown/unspecified — try the common market-execution modes FOK then IOC.
        candidate_modes = [
            (mt5.ORDER_FILLING_FOK, "FOK"),
            (mt5.ORDER_FILLING_IOC, "IOC"),
        ]
    else:
        if fm & 1:  # SYMBOL_FILLING_FOK
            candidate_modes.append((mt5.ORDER_FILLING_FOK, "FOK"))
        if fm & 2:  # SYMBOL_FILLING_IOC
            candidate_modes.append((mt5.ORDER_FILLING_IOC, "IOC"))

    last_check = None
    chosen_mode = None
    chosen_name = None
    for mode, name in candidate_modes:
        attempt = dict(request)
        attempt["type_filling"] = mode
        check = mt5.order_check(attempt)
        if check is None:
            last_check = None
            continue
        last_check = check
        if _order_check_passed(check):
            chosen_mode = mode
            chosen_name = name
            break

    if chosen_mode is None:
        return {
            "status": "rejected",
            "rejection_reason": (
                f"order_check failed for all filling modes: retcode "
                f"{getattr(last_check, 'retcode', '?')} "
                f"({getattr(last_check, 'comment', '') or ''})"
            ),
            "order_check_retcode": getattr(last_check, "retcode", None) if last_check else None,
            "order_check_comment": getattr(last_check, "comment", "") or "" if last_check else "",
            "type_filling_used": None,
            "filling_mode_candidates": [n for _, n in candidate_modes],
            "symbol_filling_mode": fm,
            "requested_units": request.get("requested_units"),
            "calculated_lots": request.get("calculated_lots"),
            "normalized_lots": vol,
            "volume_min": volume_min,
            "volume_step": volume_step,
            "volume_max": volume_max,
            "broker_mode": broker_mode,
        }

    request["type_filling"] = chosen_mode
    check = last_check

    # --- live send ---
    result = mt5.order_send(request)
    if not _order_send_succeeded(mt5, result):
        rc = int(getattr(result, "retcode", -1))
        return {
            "status": "rejected",
            "rejection_reason": f"mt5 {trade_retcode_name(mt5, rc)} ({rc})",
            "mt5_retcode": rc,
            "mt5_retcode_name": trade_retcode_name(mt5, rc),
            "mt5_comment": getattr(result, "comment", "") or "",
            "sent_volume": vol,
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

    # order_send succeeded. Distinguish terminal states:
    #   DONE (10009): fully filled.
    #   DONE_PARTIAL (10010): partially filled -> persist actual volume + flag.
    #   PLACED (10008): accepted/placed -> do NOT claim filled until
    #                   position/deal confirmation (we surface deal/order ids).
    retcode = int(getattr(result, "retcode", 1))
    filled_volume = float(getattr(result, "volume", 0.0))
    requested_volume = float(vol or 0.0)
    is_partial = (
        retcode == int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010))
        or (requested_volume > 0 and 0 < filled_volume < requested_volume)
    )
    return {
        "status": "placed" if retcode == int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)) else "filled",
        "partial": is_partial,
        "order_id": str(getattr(result, "order", "")),
        "deal_id": str(getattr(result, "deal", "")),
        "position_id": str(getattr(result, "position", "")),
        "filled_entry": float(getattr(result, "price", 0.0)),
        "filled_volume": filled_volume,
        "requested_volume": requested_volume,
        "sent_volume": vol,
        "mt5_retcode": retcode,
        "mt5_retcode_name": trade_retcode_name(mt5, retcode),
        "mt5_comment": getattr(result, "comment", "") or "",
        "spread_at_entry": request.get("spread_at_entry", 0.0),
        "slippage": 0.0,
        "broker_mode": broker_mode,
        "type_filling_used": request.get("type_filling"),
        "type_filling_name": chosen_name,
        "volume": vol,
    }
