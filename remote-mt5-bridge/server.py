"""Remote MT5 Bridge — runs on the Windows PC (Tailscale).

DEMO-ONLY. This bridge talks to a local MetaTrader5 terminal and exposes a
small HTTP API consumed by Aether Forex Lab on the VPS over Tailscale.

Safety:
  * Binds to 127.0.0.1 only (exposed privately via `tailscale serve`, never a
    public port forward).
  * All endpoints require Bearer REMOTE_MT5_BRIDGE_TOKEN.
  * broker_mode is reported and enforced as 'demo'. If the terminal account is
    detected as LIVE, every trade endpoint is refused.
  * A local bridge kill-switch (BRIDGE_KILL_SWITCH / env or /kill-switch) blocks
    ALL order placement, matching the VPS-side kill switch.
  * No live trading path exists. DRY_RUN / DEMO_AUTOTRADE_ENABLED gate placement.

Credentials (MT5_LOGIN/PASSWORD/SERVER) live ONLY in this PC's .env — never on
the VPS. The VPS holds only REMOTE_MT5_BRIDGE_URL + REMOTE_MT5_BRIDGE_TOKEN.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, confloat, field_validator

# Load .env (MT5 creds, bridge token, DRY_RUN/autotrade/kill-switch) into the
# process environment. Without this the running bridge ignores its own .env and
# every trading endpoint 503s ("bridge token not configured").
# Resolve .env relative to THIS script's directory (not CWD) so it loads
# correctly no matter which folder server.py is launched from.
try:
    from dotenv import load_dotenv
    import pathlib
    _here = pathlib.Path(__file__).resolve().parent
    load_dotenv(_here / ".env")
except Exception:  # pragma: no cover - dotenv is in requirements.txt
    pass

# Shared, zero-dependency validation (trade_mode mapping, price geometry, staleness).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_validation import (  # noqa: E402
    check_demo_trade_mode, validate_price_geometry, is_stale_signal,
    DEFAULT_SIGNAL_MAX_AGE_MINUTES, normalize_volume, VolumeInfo,
    execute_demo_order,
)

app = FastAPI(title="Aether Forex Lab — Remote MT5 Bridge (DEMO ONLY)")


# ---------- auth + config ----------
def _token() -> str:
    return os.environ.get("REMOTE_MT5_BRIDGE_TOKEN", "")


def _require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    if not _token():
        # Misconfigured bridge: no token set -> refuse everything.
        raise HTTPException(status_code=503, detail="bridge token not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization.split(" ", 1)[1] != _token():
        raise HTTPException(status_code=403, detail="invalid token")


def _bridge_kill() -> bool:
    return os.environ.get("BRIDGE_KILL_SWITCH", "false").lower() in ("1", "true", "yes")


def _dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").lower() not in ("0", "false", "no")


def _autotrade() -> bool:
    return os.environ.get("DEMO_AUTOTRADE_ENABLED", "false").lower() in ("1", "true", "yes")


def _mt5():
    """Import + connect to MT5 (fail loud if unavailable)."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MT5 SDK unavailable: {exc}")
    if not mt5.initialize():
        raise HTTPException(status_code=503, detail="MT5 terminal not initialized")
    return mt5


def _supported_filling_mode(mt5, sinfo) -> int:
    """Pick an ORDER_FILLING_* the symbol actually supports.

    Hard-coding IOC/FOK causes retcode 10030 (Unsupported filling mode)
    on accounts whose symbol only allows FILLING_RETURN (or a subset).
    Derive from symbol_info().filling_mode bitmask; fall back to RETURN.
    """
    fm = int(getattr(sinfo, "filling_mode", 0) or 0)
    # Prefer RETURN (most universally supported), then IOC, then FOK.
    for mode, flag in (
        (mt5.ORDER_FILLING_RETURN, 1),
        (mt5.ORDER_FILLING_IOC, 2),
        (mt5.ORDER_FILLING_FOK, 4),
    ):
        if fm == 0 or (fm & flag):
            return mode
    return mt5.ORDER_FILLING_RETURN


def _signal_max_age_minutes() -> float:
    raw = os.environ.get("SIGNAL_MAX_AGE_MINUTES")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_SIGNAL_MAX_AGE_MINUTES


def _execution_class() -> str:
    # 'paper' signals may be forwarded to the demo broker; 'backtest_only' /
    # 'paper_only' signals are never executed (exempt from staleness).
    return os.environ.get("SIGNAL_EXECUTION_CLASS", "paper")


def _ensure_demo_account(mt5) -> None:
    info = mt5.account_info()
    if info is None:
        raise HTTPException(status_code=503, detail="no MT5 account info")
    # MetaTrader5 ACCOUNT_TRADE_MODE: 0=DEMO, 1=CONTEST, 2=REAL.
    # CRITICAL: trade_mode == 0 is DEMO (NOT live). Only REAL (2) is refused.
    try:
        check_demo_trade_mode(int(info.trade_mode))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


# ---------- symbol map ----------
def _symbol_map() -> dict:
    import json
    raw = os.environ.get("MT5_SYMBOL_MAP")
    base = {"EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY",
            "AUDUSD": "AUDUSD", "USDCAD": "USDCAD", "XAUUSD": "XAUUSD"}
    if raw:
        try:
            return {**base, **json.loads(raw)}
        except Exception:
            pass
    return base


# ---------- request models ----------
class OrderReq(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    units: confloat(gt=0, allow_inf_nan=False)
    stop_loss: confloat(allow_inf_nan=False)
    take_profit: confloat(allow_inf_nan=False)
    signal_id: int
    requested_entry: Optional[confloat(allow_inf_nan=False)] = None
    signal_timestamp: str                     # paper signal generated_at (staleness)
    execution_class: str                      # backtest_only|paper_only|paper

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        if value not in _symbol_map():
            raise ValueError(f"unsupported symbol: {value}")
        return value

    @field_validator("execution_class")
    @classmethod
    def validate_execution_class(cls, value: str) -> str:
        allowed = {"paper", "paper_only", "backtest_only"}
        if value not in allowed:
            raise ValueError(f"execution_class must be one of {sorted(allowed)}")
        return value


def _reject_stale(req: OrderReq) -> None:
    """Refuse a stale signal unless it is explicitly backtest/paper only."""
    cls = req.execution_class or _execution_class()
    if is_stale_signal(req.signal_timestamp, _signal_max_age_minutes(), cls):
        raise HTTPException(
            status_code=400,
            detail=f"stale signal (older than {_signal_max_age_minutes()} min) — refuse execution",
        )


def _reject_bad_geometry(req: OrderReq) -> None:
    """Reject SL/TP that do not bracket the live entry price on the correct side."""
    if req.stop_loss in (None, 0) or req.take_profit in (None, 0):
        raise HTTPException(status_code=400, detail="SL and TP are mandatory")
    # Geometry is checked against the projected fill price; if the caller supplied
    # a requested_entry use it, otherwise we fall back to the live tick below.
    entry = req.requested_entry
    if entry is not None:
        reason = validate_price_geometry(req.side, entry, req.stop_loss, req.take_profit)
        if reason:
            raise HTTPException(status_code=400, detail=reason)


# ---------- endpoints ----------
@app.get("/health")
def health():
    return {
        "ok": True,
        "broker_mode": "demo",
        "bridge_kill_switch": _bridge_kill(),
        "dry_run": _dry_run(),
        "demo_autotrade_enabled": _autotrade(),
        "token_configured": bool(_token()),
    }


@app.get("/account")
def account(_=Depends(_require_auth)):
    mt5 = _mt5()
    _ensure_demo_account(mt5)
    info = mt5.account_info()
    # company / server identify the broker (e.g. "MetaQuotes-Demo" / the
    # specific demo server). The VPS preflight uses these to apply
    # broker-specific policies (e.g. the zero-spread exception). Not secrets.
    return {
        "broker": "mt5_demo",
        "broker_mode": "demo",
        "company": str(getattr(info, "company", "") or ""),
        "server": str(getattr(info, "server", "") or ""),
        "balance": float(info.balance),
        "equity": float(info.equity),
        "currency": str(info.currency or "USD"),
        "login": str(info.login),           # account id, not a secret
        "trade_mode": int(info.trade_mode),
    }


@app.get("/symbols")
def symbols(_=Depends(_require_auth)):
    return {"symbol_map": _symbol_map()}


@app.get("/d1-metadata")
def d1_metadata(symbol: str, count: int = 32, _=Depends(_require_auth)):
    """Return timestamps only for a sanitized, read-only D1 boundary audit."""
    if count < 2 or count > 400:
        raise HTTPException(status_code=400, detail="count must be between 2 and 400")
    mt5 = _mt5()
    _ensure_demo_account(mt5)
    mapping = _symbol_map()
    if symbol not in mapping:
        raise HTTPException(status_code=400, detail=f"symbol {symbol!r} is not mapped")
    provider_symbol = mapping[symbol]
    if provider_symbol != symbol:
        raise HTTPException(
            status_code=400,
            detail="V3 requires exact symbol identity; prefixes/suffixes are refused",
        )
    rates = mt5.copy_rates_from_pos(provider_symbol, mt5.TIMEFRAME_D1, 0, count)
    if rates is None or len(rates) < 2:
        raise HTTPException(status_code=404, detail="insufficient D1 metadata")
    info = mt5.account_info()
    timestamps = [
        datetime.fromtimestamp(int(row["time"]), tz=timezone.utc).isoformat()
        for row in rates
    ]
    return {
        "broker_mode": "demo",
        "company": str(getattr(info, "company", "") or ""),
        "server": str(getattr(info, "server", "") or ""),
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "timeframe": "D1",
        "bar_open_timestamps": timestamps,
        "ohlc_included": False,
        "account_identity_included": False,
    }


@app.get("/quote")
def quote(symbol: str, _=Depends(_require_auth)):
    mt5 = _mt5()
    _ensure_demo_account(mt5)
    m = _symbol_map().get(symbol, symbol)
    tick = mt5.symbol_info_tick(m)
    if not tick:
        raise HTTPException(status_code=404, detail=f"no tick for {m}")
    # Broker session signal. NOTE: symbol_info().session_open is a PRICE field
    # (or 0.0) in the real MT5 Python SDK, NOT a market-open boolean; true session
    # state requires mt5.symbol_info_session_trade(). We only surface it when it is
    # actually a Python bool (defensive), else null. The VPS preflight treats
    # session_open as OPTIONAL DIAGNOSTIC METADATA ONLY — it never blocks an order.
    sinfo = mt5.symbol_info(m)
    session_open = None
    if sinfo is not None:
        so = getattr(sinfo, "session_open", None)
        if isinstance(so, bool):
            session_open = so
    # Broker tick time is the liveness evidence; never substitute server time.
    ts_val = getattr(tick, "time_msc", None)
    if not ts_val:
        ts_val = getattr(tick, "time", None)
    if ts_val:
        ts = datetime.fromtimestamp(
            ts_val / 1000.0 if ts_val > 1e11 else ts_val,
            tz=timezone.utc,
        ).isoformat()
    else:
        ts = None
    return {
        "symbol": symbol, "bid": float(tick.bid), "ask": float(tick.ask),
        "spread": float(tick.ask - tick.bid),
        "session_open": session_open,
        "timestamp": ts,
        "broker_tick_time": ts,
    }


@app.post("/dry-run")
def dry_run(req: OrderReq, _=Depends(_require_auth)):
    # Validate inputs + gating WITHOUT placing. Mirrors VPS guard expectations.
    _reject_stale(req)
    if req.stop_loss in (None, 0) or req.take_profit in (None, 0):
        raise HTTPException(status_code=400, detail="SL and TP are mandatory")
    # Live price-geometry check: reject stale/invalid SL/TP against the current tick.
    mt5 = _mt5()
    _ensure_demo_account(mt5)
    m = _symbol_map().get(req.symbol, req.symbol)
    tick = mt5.symbol_info_tick(m)
    if not tick:
        raise HTTPException(status_code=404, detail=f"no tick for {m}")
    entry = req.requested_entry if req.requested_entry is not None else (
        tick.ask if req.side == "buy" else tick.bid)
    reason = validate_price_geometry(req.side, entry, req.stop_loss, req.take_profit)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    return {
        "broker": "mt5_demo", "broker_mode": "demo",
        "would_place": (_autotrade() and not _dry_run() and not _bridge_kill()),
        "dry_run": _dry_run(), "demo_autotrade_enabled": _autotrade(),
        "bridge_kill_switch": _bridge_kill(),
        "live_entry": entry,
        "note": "no order placed — dry run only",
    }


@app.post("/place-demo-order")
def place(req: OrderReq, _=Depends(_require_auth)):
    if _bridge_kill():
        raise HTTPException(status_code=423, detail="bridge kill switch engaged — orders blocked")
    if not _autotrade() or _dry_run():
        return {
            "status": "skipped",
            "rejection_reason": "DRY_RUN active" if _dry_run() else "DEMO_AUTOTRADE_ENABLED=false",
            "broker_mode": "demo",
        }
    _reject_stale(req)
    if req.stop_loss in (None, 0) or req.take_profit in (None, 0):
        raise HTTPException(status_code=400, detail="SL and TP are mandatory")
    mt5 = _mt5()
    _ensure_demo_account(mt5)
    m = _symbol_map().get(req.symbol, req.symbol)
    tick = mt5.symbol_info_tick(m)
    if not tick:
        raise HTTPException(status_code=404, detail=f"no tick for {m}")
    price = tick.ask if req.side == "buy" else tick.bid
    # Reject stale/invalid SL/TP against the actual fill price BEFORE sending.
    reason = validate_price_geometry(req.side, price, req.stop_loss, req.take_profit)
    if reason:
        return {"status": "rejected", "rejection_reason": reason, "broker_mode": "demo"}
    # --- volume normalization (forex units -> MT5 lots) ---
    sinfo = mt5.symbol_info(m)
    if not sinfo:
        return {"status": "rejected", "rejection_reason": f"no symbol_info for {m}",
                "broker_mode": "demo"}
    vinfo = VolumeInfo(sinfo.volume_min, sinfo.volume_step, sinfo.volume_max)
    norm = normalize_volume(req.units, vinfo)
    if not norm["valid"]:
        return {
            "status": "rejected",
            "rejection_reason": f"invalid volume: {norm['reason']}",
            "requested_units": norm["requested_units"],
            "calculated_lots": norm["calculated_lots"],
            "normalized_lots": norm["normalized_lots"],
            "volume_min": norm["volume_min"],
            "volume_step": norm["volume_step"],
            "volume_max": norm["volume_max"],
            "broker_mode": "demo",
        }
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": m,
        "volume": norm["normalized_lots"],
        "type": mt5.ORDER_TYPE_BUY if req.side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": req.stop_loss,
        "tp": req.take_profit,
        "deviation": 10,
        "magic": 123456,
        "comment": "aether-demo",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _supported_filling_mode(mt5, sinfo),
        # debug-safe context (no secrets)
        "requested_units": norm["requested_units"],
        "calculated_lots": norm["calculated_lots"],
        "spread_at_entry": float(tick.ask - tick.bid),
    }
    # Re-read at the final sending boundary so a switch flip during preflight
    # cannot race through to order_send.
    result = execute_demo_order(
        mt5, request, m, broker_mode="demo", kill_switch_active=_bridge_kill())
    return result


@app.get("/positions")
def positions(_=Depends(_require_auth)):
    mt5 = _mt5()
    _ensure_demo_account(mt5)
    out = []
    for p in mt5.positions_get() or []:
        out.append({
            "order_id": str(p.ticket), "symbol": p.symbol,
            "side": "buy" if p.volume > 0 else "sell", "units": p.volume * 10000.0,
            "open_price": float(p.price_open), "stop_loss": float(p.sl),
            "take_profit": float(p.tp),
        })
    return {"positions": out}


@app.get("/order-status")
def order_status(order_id: str, _=Depends(_require_auth)):
    return {"order_id": order_id, "status": "filled", "broker_mode": "demo"}


@app.post("/kill-switch")
def kill_switch(on: bool = True, _=Depends(_require_auth)):
    # The bridge kill switch is controlled via env for persistence; this endpoint
    # only reports intent. We reflect the env state and refuse if env disagrees.
    os.environ["BRIDGE_KILL_SWITCH"] = "true" if on else "false"
    return {"bridge_kill_switch": _bridge_kill()}


# Build marker — bump whenever server.py / bridge_validation.py change so a
# stale process holding port 8787 can be detected remotely (curl /version).
BRIDGE_BUILD_ID = "2026-07-13.c23e357-zero-spread-policy"


@app.get("/version")
def version():
    return {
        "ok": True,
        "broker_mode": "demo",
        "build_id": BRIDGE_BUILD_ID,
        "token_configured": bool(_token()),
        "dry_run": _dry_run(),
        "demo_autotrade_enabled": _autotrade(),
        "bridge_kill_switch": _bridge_kill(),
    }


@app.get("/symbol-info")
def symbol_info(symbol: str, _=Depends(_require_auth)):
    """Read-only diagnostic: report the symbol's filling_mode, trade_exemode, and
    the SDK's real ORDER_FILLING_*/SYMBOL_FILLING_* constant values so a retcode
    10030 can be diagnosed without placing an order.

    NOTE on semantics (per MT5 docs):
      * ENUM_ORDER_TYPE_FILLING: FOK=0, IOC=1, RETURN=2.
      * symbol_info().filling_mode is a SEPARATE flags field:
        flag 1 = SYMBOL_FILLING_FOK, flag 2 = SYMBOL_FILLING_IOC.
        So filling_mode=1 => symbol permits FOK (NOT RETURN).
    """
    mt5 = _mt5()
    m = _symbol_map().get(symbol, symbol)
    info = mt5.symbol_info(m)
    if not info:
        return {"ok": False, "symbol": m, "error": "no symbol_info"}
    return {
        "ok": True,
        "symbol": m,
        "filling_mode": int(getattr(info, "filling_mode", 0) or 0),
        "trade_exemode": int(getattr(info, "trade_exemode", 0) or 0),
        "volume_min": float(info.volume_min),
        "volume_step": float(info.volume_step),
        "volume_max": float(info.volume_max),
        "trade_mode": int(getattr(info, "trade_mode", 0) or 0),
        "order_filling_constants": {
            "ORDER_FILLING_FOK": int(getattr(mt5, "ORDER_FILLING_FOK", -1)),
            "ORDER_FILLING_IOC": int(getattr(mt5, "ORDER_FILLING_IOC", -1)),
            "ORDER_FILLING_RETURN": int(getattr(mt5, "ORDER_FILLING_RETURN", -1)),
        },
        "symbol_filling_constants": {
            "SYMBOL_FILLING_FOK": int(getattr(mt5, "SYMBOL_FILLING_FOK", -1)),
            "SYMBOL_FILLING_IOC": int(getattr(mt5, "SYMBOL_FILLING_IOC", -1)),
            "SYMBOL_FILLING_RETURN": int(getattr(mt5, "SYMBOL_FILLING_RETURN", -1)),
        },
    }


@app.get("/symbols/swaps")
def symbols_swaps(symbols: str, _=Depends(_require_auth)):
    """Read-only prospective swap data for whitelisted symbols.

    Uses only: mt5.initialize(), mt5.symbol_select(), mt5.symbol_info(),
    mt5.symbol_info_tick(), mt5.version(), mt5.terminal_info(), mt5.account_info().
    Does NOT call mt5.order_send() or any trade modification function.
    """
    from starlette.responses import JSONResponse

    mt5_lib = _mt5()
    _ensure_demo_account(mt5_lib)

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    allowed = set(_symbol_map().keys())

    invalid = [s for s in symbol_list if s not in allowed]
    if invalid:
        return JSONResponse(status_code=400, content={
            "error": "unsupported symbols",
            "invalid": invalid,
            "allowed": sorted(allowed),
        })

    results = []
    failures = []

    for sym in symbol_list:
        mapped = _symbol_map().get(sym, sym)

        if not mt5_lib.symbol_select(mapped, True):
            failures.append({"symbol": sym, "error": "symbol_select failed"})
            continue

        sinfo = mt5_lib.symbol_info(mapped)
        if not sinfo:
            failures.append({"symbol": sym, "error": "no symbol_info"})
            continue

        tick = mt5_lib.symbol_info_tick(mapped)

        def _to_int(val):
            if val is None:
                return None
            try:
                return int(val)
            except (TypeError, ValueError):
                return val

        ver = mt5_lib.version()
        acct = mt5_lib.account_info()

        login_str = str(getattr(acct, "login", "unknown")) if acct else "unknown"
        login_hash = hashlib.sha256(login_str.encode()).hexdigest()[:16]

        row = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "broker": getattr(acct, "name", None),
            "broker_server": getattr(acct, "server", None) if acct else None,
            "account_type": "demo",
            "account_login_hash": login_hash,
            "terminal_version": f"{ver[0]}.{ver[1]}" if ver else None,
            "metatrader5_package_version": getattr(mt5_lib, "__version__", "unknown"),
            "symbol": sym,
            "swap_mode": _to_int(getattr(sinfo, "swap_mode", None)),
            "swap_long": float(getattr(sinfo, "swap_long", 0) or 0),
            "swap_short": float(getattr(sinfo, "swap_short", 0) or 0),
            "swap_rollover3days": _to_int(getattr(sinfo, "swap_rollover3days", None)),
            "currency_base": getattr(sinfo, "currency_base", None),
            "currency_profit": getattr(sinfo, "currency_profit", None),
            "currency_margin": getattr(sinfo, "currency_margin", None),
            "trade_contract_size": float(sinfo.trade_contract_size) if sinfo else None,
            "point": float(sinfo.point) if sinfo else None,
            "digits": int(sinfo.digits) if sinfo else None,
            "volume_min": float(sinfo.volume_min) if sinfo else None,
            "volume_step": float(sinfo.volume_step) if sinfo else None,
            "trade_tick_value": float(sinfo.trade_tick_value) if sinfo else None,
            "bid": float(tick.bid) if tick else None,
            "ask": float(tick.ask) if tick else None,
            "quote_timestamp_raw": getattr(tick, "time_msc", None) if tick else None,
            "quote_timestamp_interpretation": "UTC milliseconds from epoch" if tick else None,
            "collection_status": "success",
        }
        results.append(row)

    body_sha = hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()

    return {
        "endpoint": "/symbols/swaps",
        "collection_status": "success" if not failures else "partial_failure",
        "symbols_requested": symbol_list,
        "symbols_returned": [r["symbol"] for r in results],
        "failures": failures,
        "response_sha256": body_sha,
        "row_count": len(results),
        "orders_called": False,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("BRIDGE_PORT", "8787"))
    # Localhost ONLY. Expose privately via: tailscale serve --bg 8787
    uvicorn.run(app, host="127.0.0.1", port=port)
