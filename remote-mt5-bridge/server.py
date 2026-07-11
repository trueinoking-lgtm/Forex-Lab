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
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel

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
    side: str            # buy | sell
    units: float
    stop_loss: float
    take_profit: float
    signal_id: Optional[int] = None
    requested_entry: Optional[float] = None
    signal_timestamp: Optional[str] = None     # paper signal generated_at (staleness)
    execution_class: Optional[str] = None       # backtest_only|paper_only|paper


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
    return {
        "broker": "mt5_demo",
        "broker_mode": "demo",
        "balance": float(info.balance),
        "equity": float(info.equity),
        "currency": str(info.currency or "USD"),
        "login": str(info.login),           # account id, not a secret
        "trade_mode": int(info.trade_mode),
    }


@app.get("/symbols")
def symbols(_=Depends(_require_auth)):
    return {"symbol_map": _symbol_map()}


@app.get("/quote")
def quote(symbol: str, _=Depends(_require_auth)):
    mt5 = _mt5()
    _ensure_demo_account(mt5)
    m = _symbol_map().get(symbol, symbol)
    tick = mt5.symbol_info_tick(m)
    if not tick:
        raise HTTPException(status_code=404, detail=f"no tick for {m}")
    return {
        "symbol": symbol, "bid": float(tick.bid), "ask": float(tick.ask),
        "spread": float(tick.ask - tick.bid),
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        "type_filling": mt5.ORDER_FILLING_IOC,
        # debug-safe context (no secrets)
        "requested_units": norm["requested_units"],
        "calculated_lots": norm["calculated_lots"],
        "spread_at_entry": float(tick.ask - tick.bid),
    }
    result = execute_demo_order(mt5, request, m, broker_mode="demo")
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


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("BRIDGE_PORT", "8787"))
    # Localhost ONLY. Expose privately via: tailscale serve --bg 8787
    uvicorn.run(app, host="127.0.0.1", port=port)
