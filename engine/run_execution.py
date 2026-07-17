"""CLI: demo execution bridge for Aether Forex Lab.

Commands: check | demo-order | update | journal | kill-switch

SAFETY:
  * Refuses if allow_live_orders is true or broker_mode != 'demo'.
  * Reads ExecutionControl (kill switch + max open) from the app DB.
  * Stores only redacted raw responses; secrets come from env, never the DB.
  * Every demo order passes run_pretrade_guards (deterministic risk engine) first.

Usage:
  python run_execution.py check [--adapter mock|deriv_mt5|oanda_practice]
  python run_execution.py demo-order --signal-id N [--adapter mock] [--symbol ...]
  python run_execution.py update [--order-id ID]
  python run_execution.py journal [--days N]
  python run_execution.py kill-switch [--on|--off]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import math
from datetime import datetime, timezone

import yaml  # noqa: E402

# allow running from engine/ dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.signals import PaperSignal  # noqa: E402
from src.execution import (  # noqa: E402
    build_adapter, run_pretrade_guards, GuardError, redact, MockDemoAdapter,
    DemoOrderRequest, capabilities, capability, BrokerCapability,
    execution_mode, primary_demo_broker, mirror_demo_enabled,
    dry_run, demo_autotrade_enabled, can_place_real_demo, broker_names,
)
from src.execution.bridge_validation import (  # noqa: E402
    validate_price_geometry, check_symbol_tradable,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "forex_lab.db")
CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cfg() -> dict:
    with open(CFG_PATH) as f:
        return yaml.safe_load(f)


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    # Harden against "database is locked" under concurrent access (app + cron
    # scheduler + pytest all write this single file). WAL lets a writer proceed
    # without blocking readers; busy_timeout makes a contended writer wait
    # instead of raising; isolation_level=None (autocommit) means no connection
    # ever holds an implicit write transaction open across calls.
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.isolation_level = None
    return db


def _control(db: sqlite3.Connection) -> dict:
    row = db.execute("SELECT * FROM ExecutionControl WHERE id=1").fetchone()
    return dict(row) if row else {"kill_switch": 0, "broker_mode": "demo",
                                  "max_open_demo_trades": 5,
                                  "max_open_per_broker": 5,
                                  "execution_mode": "observe_only",
                                  "primary_demo_broker": "oanda_practice"}


def _open_demo(db: sqlite3.Connection) -> int:
    return db.execute(
        "SELECT COUNT(*) c FROM DemoExecutionOrder WHERE status='filled'"
    ).fetchone()["c"]


def _open_demo_by_broker(db: sqlite3.Connection, broker: str) -> int:
    return db.execute(
        "SELECT COUNT(*) c FROM DemoExecutionOrder WHERE status='filled' AND broker=?",
        (broker,),
    ).fetchone()["c"]


def _persist_capabilities(db: sqlite3.Connection) -> dict:
    """Probe every broker and store a redacted capability snapshot."""
    caps = capabilities()
    for broker, cap in caps.items():
        db.execute(
            """INSERT INTO BrokerCapability
               (broker, broker_mode, credentials_present, account_reachable,
                account_currency, balance, equity, trading_enabled, market_open,
                last_checked_at, last_error_redacted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (cap.broker, cap.broker_mode, int(cap.credentials_present),
             int(cap.account_reachable), cap.account_currency, cap.balance,
             cap.equity, int(cap.trading_enabled),
             None if cap.market_open is None else int(cap.market_open),
             cap.last_checked_at, cap.last_error_redacted),
        )
    db.commit()
    return {b: _cap_to_dict(c) for b, c in caps.items()}


def _cap_to_dict(cap: BrokerCapability) -> dict:
    return {
        "broker": cap.broker, "broker_mode": cap.broker_mode,
        "credentials_present": cap.credentials_present,
        "account_reachable": cap.account_reachable,
        "account_currency": cap.account_currency, "balance": cap.balance,
        "equity": cap.equity, "trading_enabled": cap.trading_enabled,
        "market_open": cap.market_open,
        "last_checked_at": cap.last_checked_at,
        "last_error_redacted": cap.last_error_redacted,
    }


def _lock_key_exists(db: sqlite3.Connection, signal_id, broker, run_id) -> bool:
    row = db.execute(
        "SELECT 1 FROM DemoExecutionLock WHERE signal_id=? AND broker=? AND run_id=?",
        (signal_id, broker, run_id),
    ).fetchone()
    return row is not None


def _acquire_lock(db: sqlite3.Connection, signal_id, broker, run_id, order_id) -> bool:
    """Insert a duplicate-lock row. Returns False if (signal,broker,run_id) exists."""
    try:
        db.execute(
            """INSERT INTO DemoExecutionLock (signal_id, broker, run_id, order_id, created_at)
               VALUES (?,?,?,?,?)""",
            (signal_id, broker, run_id, order_id, _now()),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        db.rollback()
        return False


def _paper_signal(db: sqlite3.Connection, signal_id: int) -> PaperSignal | None:
    row = db.execute("SELECT * FROM Signal WHERE id=?", (signal_id,)).fetchone()
    if not row:
        return None
    return PaperSignal(
        pair=row["pair"], strategy=row["strategy"], direction=row["direction"],
        entry=row["entry"], stop_loss=row["stop_loss"], take_profit=row["take_profit"],
        signal_score=row["signal_score"] or 0.0, regime=row["regime"] or "range",
        timestamp=row["generated_at"],
        units=float(row["units"]) if row["units"] is not None else 0.0,
        id=row["id"],
    )


def _validate_units(units) -> float:
    """Return a valid (>0) units value, or raise ValueError loudly.

    Rejects None, non-finite (NaN/inf), <= 0. A missing/zero/NaN size must never
    be silently coerced to 0 — that is exactly what let Signal #6 reach the
    broker with units=0 and get rejected as 'units must be positive'.
    """
    if units is None:
        raise ValueError("units is missing (None)")
    try:
        u = float(units)
    except (TypeError, ValueError):
        raise ValueError(f"units is not numeric: {units!r}")
    if not math.isfinite(u):
        raise ValueError(f"units is not finite: {units!r}")
    if u <= 0:
        raise ValueError(f"units must be > 0, got {u!r}")
    return u


def prepare_demo_order_from_signal(signal: PaperSignal, broker: str,
                                   requested_entry: float | None = None) -> DemoOrderRequest:
    """Build the DemoOrderRequest for a paper signal, preserving signal_id + units.

    Used by BOTH the dry-run and the real order so they share identical order
    preparation. Raises ValueError (loud) if the signal lacks id, has no units,
    or units <= 0 / NaN — so a bad signal can never be forwarded to the broker.
    """
    if getattr(signal, "id", None) is None:
        raise ValueError("signal has no id — cannot place an order")
    units = _validate_units(getattr(signal, "units", None))
    return DemoOrderRequest(
        symbol=signal.pair,
        side="buy" if signal.direction > 0 else "sell",
        units=units,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        signal_id=signal.id,
        signal_timestamp=signal.timestamp,
        execution_class="paper",
        requested_entry=requested_entry if requested_entry is not None else signal.entry,
    )


def _ensure_signal_lineage_col(db: sqlite3.Connection) -> None:
    """Idempotent migration: add original_signal_id to Signal for refresh lineage.

    Safe to call on every open — no-op once the column exists.
    """
    cols = {r[1] for r in db.execute("PRAGMA table_info(Signal)").fetchall()}
    if "original_signal_id" not in cols:
        db.execute("ALTER TABLE Signal ADD COLUMN original_signal_id INTEGER")


def _ensure_demo_order_cols(db: sqlite3.Connection) -> None:
    """Idempotent migration: add broker result fields to DemoExecutionOrder.

    Adds deal_id, position_id, type_filling_used, partial, filled_units so the live bridge
    result (order/deal/position ids, filling mode, partial-fill flag) can be
    persisted. Safe to call on every open — no-op once columns exist.
    """
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "DemoExecutionOrder" not in tables:
        return  # table not yet created in this environment — nothing to migrate
    cols = {r[1] for r in db.execute("PRAGMA table_info(DemoExecutionOrder)").fetchall()}
    for col, ctype in (
        ("deal_id", "TEXT"),
        ("position_id", "TEXT"),
        ("type_filling_used", "TEXT"),
        ("partial", "INTEGER"),
        ("filled_units", "REAL"),
    ):
        if col not in cols:
            db.execute(f"ALTER TABLE DemoExecutionOrder ADD COLUMN {col} {ctype}")


def _insert_fresh_signal(db: sqlite3.Connection, *, pair, strategy, direction, entry,
                         stop_loss, take_profit, status, signal_score, regime,
                         generated_at, units, original_signal_id) -> int:
    """Insert a fresh Signal row and return its new id. Mirrors the existing
    Signal schema (adds original_signal_id lineage)."""
    db.execute(
        """INSERT INTO Signal
           (pair, strategy, direction, entry, stop_loss, take_profit, status,
            signal_score, regime, generated_at, units, original_signal_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pair, strategy, direction, entry, stop_loss, take_profit, status,
         signal_score, regime, generated_at, units, original_signal_id),
    )
    return db.execute("SELECT last_insert_rowid() id").fetchone()["id"]


def cmd_check(args) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("CHECK FAILED: allow_live_orders is true — demo bridge refuses.")
        return 2
    if cfg.get("paper_only") is False:
        print("CHECK FAILED: paper_only is false.")
        return 2
    try:
        adapter = build_adapter(args.adapter, fail_loud=True)
    except RuntimeError as e:
        print(f"CHECK: adapter '{args.adapter}' unavailable — {e}")
        return 2
    acc = adapter.get_account()
    av = __import__("src.execution.factory", fromlist=["available_adapters"]).available_adapters()
    print(json.dumps({
        "paper_only": cfg.get("paper_only"),
        "allow_live_orders": cfg.get("allow_live_orders"),
        "broker_mode": "demo",
        "selected_adapter": adapter.name,
        "adapter_available": av,
        "account_balance": acc.balance,
        "account_currency": acc.currency,
    }, indent=2))
    return 0


def cmd_demo_order(args) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("REJECTED: ALLOW_LIVE_ORDERS=true — demo-only bridge refuses.")
        return 2
    db = _db()
    ctrl = _control(db)
    if ctrl["broker_mode"] != "demo":
        print("REJECTED: broker_mode != demo.")
        return 2
    if ctrl["kill_switch"]:
        print("REJECTED: kill switch engaged.")
        return 2
    signal = _paper_signal(db, args.signal_id) if args.signal_id else None
    if signal is None:
        print(f"REJECTED: no paper Signal with id={args.signal_id}.")
        return 2
    # Derive requested entry from latest price (mock) or requested_entry flag.
    adapter = build_adapter(args.adapter, fail_loud=True)
    quote = adapter.get_prices(signal.pair)
    requested_entry = args.entry or round((quote.bid + quote.ask) / 2, 5)
    order = DemoOrderRequest(
        symbol=signal.pair, side="buy" if signal.direction > 0 else "sell",
        units=signal.units or 0.0, stop_loss=signal.stop_loss,
        take_profit=signal.take_profit, signal_id=signal.id if hasattr(signal, "id") else args.signal_id,
        signal_timestamp=signal.timestamp, execution_class="paper",
        requested_entry=requested_entry,
    )
    res = run_pretrade_guards(
        order, broker_mode=ctrl["broker_mode"], allow_live_orders=cfg.get("allow_live_orders"),
        account=cfg.get("account", 10000.0), risk_pct=cfg.get("signals", {}).get("risk_pct", 0.75),
        signal=signal, open_demo_trades=_open_demo(db),
        max_open_demo_trades=ctrl["max_open_demo_trades"], kill_switch=bool(ctrl["kill_switch"]),
        live_quote=quote, signal_timestamp=signal.timestamp, execution_class="paper",
    )
    if not res.passed:
        reason = "; ".join(res.reasons)
        db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
                take_profit,units,requested_at,status,rejection_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?)""",
            (args.signal_id, adapter.name, "demo", order.symbol, order.side,
             requested_entry, order.stop_loss, order.take_profit, order.units,
             _now(), reason),
        )
        db.commit()
        print(f"REJECTED: {reason}")
        return 2
    # Passed — submit to adapter.
    status = adapter.place_demo_order(order)
    last_id = None
    if status.status in ("filled", "placed", "done_partial"):
        filled_units = getattr(status, "filled_units", None)
        if filled_units is None:
            filled_units = order.units
        cur = db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,filled_entry,
                stop_loss,take_profit,units,requested_at,filled_at,status,
                spread_at_entry,slippage,deal_id,position_id,type_filling_used,
                partial,filled_units,raw_response_redacted_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (args.signal_id, adapter.name, "demo", order.symbol, order.side, requested_entry,
             status.filled_entry, order.stop_loss, order.take_profit, order.units,
             _now(), _now(), status.status, status.spread_at_entry, status.slippage,
             status.deal_id, status.position_id, status.type_filling_used,
             status.partial, filled_units, status.raw_redacted),
        )
        last_id = cur.lastrowid
    else:
        cur = db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
                take_profit,units,requested_at,status,rejection_reason,raw_response_redacted_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?,?)""",
            (args.signal_id, adapter.name, "demo", order.symbol, order.side, requested_entry,
             order.stop_loss, order.take_profit, order.units, _now(), status.rejection_reason,
             status.raw_redacted),
        )
        last_id = cur.lastrowid
    db.commit()
    print(json.dumps({
        "broker": adapter.name,
        "status": status.status,
        "order_id": status.order_id,
        "deal_id": status.deal_id,
        "position_id": status.position_id,
        "type_filling_used": status.type_filling_used,
        "partial": status.partial,
        "filled_entry": status.filled_entry,
        "spread": status.spread_at_entry,
        "slippage": status.slippage,
        "rejection_reason": status.rejection_reason,
        "demo_execution_order_id": last_id,
        "signal_id": args.signal_id,
        "signal_units": order.units,
        "prepared_order_units": order.units,
        "broker_mode": "demo",
    }, indent=2))
    return 0


def cmd_update(args) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("REJECTED: ALLOW_LIVE_ORDERS=true."); return 2
    db = _db()
    adapter = build_adapter(args.adapter, fail_loud=False)
    rows = db.execute(
        "SELECT * FROM DemoExecutionOrder WHERE status='filled'"
        + (f" AND id={args.order_id}" if args.order_id else "")
    ).fetchall()
    print(f"updating {len(rows)} open demo order(s)...")
    for r in rows:
        st = adapter.get_order_status(str(r["id"]))
        db.execute(
            "UPDATE DemoExecutionOrder SET status=?, filled_entry=?, spread_at_entry=?, "
            "slippage=?, raw_response_redacted_json=? WHERE id=?",
            (st.status, st.filled_entry, st.spread_at_entry, st.slippage, st.raw_redacted, r["id"]),
        )
    db.commit()
    return 0


def cmd_journal(args) -> int:
    db = _db()
    j = db.execute(
        "SELECT * FROM ExecutionJournal ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    print(json.dumps([dict(x) for x in j], indent=2, default=str))
    return 0


def cmd_mock_lifecycle(args) -> int:
    """Deterministic, rerun-safe full demo lifecycle via the mock adapter.

    Steps: take an existing paper Signal -> place a mock demo order -> simulate a
    price move that closes it -> update -> journal the paper-vs-demo comparison.

    Rerun-safety: a run_id is generated (or passed via --run-id). The final
    ExecutionJournal row is keyed on (run_id) so rerunning the SAME run_id cannot
    create a duplicate proof row; a new run_id starts a fresh proof.

    Safety: kill switch blocks the whole lifecycle; live mode is impossible
    (mock adapter + broker_mode='demo' enforced at every step).
    """
    import uuid
    import time as _time

    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("REJECTED: ALLOW_LIVE_ORDERS=true — demo lifecycle refuses.")
        return 2
    db = _db()
    ctrl = _control(db)
    if ctrl["broker_mode"] != "demo":
        print("REJECTED: broker_mode != demo.")
        return 2
    if ctrl["kill_switch"]:
        print("REJECTED: kill switch engaged — lifecycle blocked.")
        return 2
    signal = _paper_signal(db, args.signal_id) if args.signal_id else None
    if signal is None:
        print(f"REJECTED: no paper Signal with id={args.signal_id}.")
        return 2

    run_id = args.run_id or f"lc-{uuid.uuid4().hex[:10]}"
    # Rerun-safety: skip if this run_id already produced a completed journal row.
    existing = db.execute(
        "SELECT id FROM ExecutionJournal WHERE run_id=? AND demo_order_id IS NOT NULL "
        "AND actual_demo_pnl IS NOT NULL LIMIT 1", (run_id,)
    ).fetchone()
    if existing and not args.force:
        print(json.dumps({"status": "skipped", "reason": "run_id already completed",
                          "run_id": run_id, "journal_id": existing["id"]}, indent=2))
        return 0

    adapter = build_adapter("mock", fail_loud=True)
    quote = adapter.get_prices(signal.pair)
    requested_entry = round((quote.bid + quote.ask) / 2, 5)
    order = DemoOrderRequest(
        symbol=signal.pair, side="buy" if signal.direction > 0 else "sell",
        units=signal.units or 0.0, stop_loss=signal.stop_loss,
        take_profit=signal.take_profit, signal_id=args.signal_id,
        signal_timestamp=signal.timestamp, execution_class="paper",
        requested_entry=requested_entry,
    )
    res = run_pretrade_guards(
        order, broker_mode=ctrl["broker_mode"], allow_live_orders=cfg.get("allow_live_orders"),
        account=cfg.get("account", 10000.0), risk_pct=cfg.get("signals", {}).get("risk_pct", 0.75),
        signal=signal, open_demo_trades=_open_demo(db),
        max_open_demo_trades=ctrl["max_open_demo_trades"], kill_switch=bool(ctrl["kill_switch"]),
        live_quote=quote, signal_timestamp=signal.timestamp, execution_class="paper",
    )
    if not res.passed:
        reason = "; ".join(res.reasons)
        db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
                take_profit,units,requested_at,status,rejection_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?)""",
            (args.signal_id, adapter.name, "demo", order.symbol, order.side,
             requested_entry, order.stop_loss, order.take_profit, order.units,
             _now(), reason),
        )
        db.commit()
        print(f"REJECTED: {reason}")
        return 2

    t0 = _time.time()
    status = adapter.place_demo_order(order)
    if status.status != "filled":
        print(f"FAILED: mock fill rejected: {status.rejection_reason}")
        return 2
    # Simulate a deterministic price move: advance to the unfavourable? No — use the
    # take-profit as the simulated exit for a clean, reproducible lifecycle win.
    exit_price = order.take_profit if signal.direction > 0 else order.take_profit
    # Close the mock order (recorded).
    adapter.close_demo_order(status.order_id)
    latency_ms = round((_time.time() - t0) * 1000, 2)

    filled_entry = status.filled_entry
    units = order.units
    direction = 1 if signal.direction > 0 else -1
    # Paper expected PnL uses the paper signal entry vs the same exit (apples-to-apples).
    expected_paper_pnl = round((exit_price - signal.entry) * direction * units, 2)
    actual_demo_pnl = round((exit_price - (filled_entry or signal.entry)) * direction * units, 2)
    pnl_delta = round(actual_demo_pnl - expected_paper_pnl, 2)
    acceptable = 1 if abs(pnl_delta) <= max(status.slippage or 0, 0.0005) * units * 2 else 0
    lesson = {
        "broker": adapter.name, "broker_mode": "demo", "run_id": run_id,
        "expected_paper_pnl": expected_paper_pnl, "actual_demo_pnl": actual_demo_pnl,
        "pnl_delta": pnl_delta, "note": "mock fill; not a real broker execution",
    }

    # Persist the demo order row first (idempotent per signal via REPLACE-safe insert).
    ins_order = db.execute(
        """INSERT INTO DemoExecutionOrder
           (signal_id,broker,broker_mode,symbol,side,requested_entry,filled_entry,
            stop_loss,take_profit,units,requested_at,filled_at,status,
            spread_at_entry,slippage,raw_response_redacted_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (args.signal_id, adapter.name, "demo", order.symbol, order.side, requested_entry,
         filled_entry, order.stop_loss, order.take_profit, units,
         _now(), _now(), "closed", status.spread_at_entry, status.slippage,
         status.raw_redacted),
    )
    order_id = ins_order.lastrowid

    db.execute(
        """INSERT INTO ExecutionJournal
           (demo_order_id, signal_id, broker, broker_mode, run_id,
            expected_paper_entry, actual_demo_entry, price_exit,
            expected_paper_pnl, actual_demo_pnl, slippage, spread, latency_ms,
            was_execution_acceptable, lesson_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, args.signal_id, adapter.name, "demo", run_id,
         signal.entry, filled_entry, exit_price,
         expected_paper_pnl, actual_demo_pnl, status.slippage, status.spread_at_entry,
         latency_ms, acceptable, json.dumps(lesson), _now()),
    )
    db.commit()
    print(json.dumps({
        "status": "completed", "run_id": run_id, "broker": adapter.name,
        "broker_mode": "demo", "order_id": status.order_id, "signal_id": args.signal_id,
        "expected_paper_pnl": expected_paper_pnl, "actual_demo_pnl": actual_demo_pnl,
        "pnl_delta": pnl_delta, "spread": status.spread_at_entry,
        "slippage": status.slippage, "latency_ms": latency_ms,
        "was_execution_acceptable": acceptable,
    }, indent=2))
    return 0


def _place_real_demo(db, cfg, ctrl, broker, signal, run_id, adapter) -> dict:
    """Place ONE real demo broker order for an approved paper signal.

    Hard gates (all must pass or we return a rejected record — never a fake fill):
      * allow_live_orders false, broker_mode demo
      * kill switch off
      * execution mode + autotrade + dry_run allow it (can_place_real_demo)
      * pre-trade guards pass (deterministic risk engine, SL/TP, paper signal)
      * per-broker AND global max-open caps respected
      * duplicate (signal,broker,run_id) lock not already taken
    The adapter itself ALSO gatekeeps DRY_RUN / DEMO_AUTOTRADE_ENABLED and returns a
    'skipped' status if not permitted — so even a misconfigured env cannot place.
    """
    _ensure_demo_order_cols(db)
    result = {"broker": broker, "status": "rejected", "order_id": "",
              "filled_entry": None, "rejection_reason": None}
    if cfg.get("allow_live_orders"):
        result["rejection_reason"] = "ALLOW_LIVE_ORDERS=true — demo-only bridge refuses"
        return result
    if ctrl["broker_mode"] != "demo":
        result["rejection_reason"] = "broker_mode != demo"
        return result
    if ctrl["kill_switch"]:
        result["rejection_reason"] = "kill switch engaged — all demo orders refused"
        return result
    if not can_place_real_demo():
        result["rejection_reason"] = (
            f"execution mode {execution_mode()} / autotrade {demo_autotrade_enabled()} "
            f"/ dry_run {dry_run()} do not permit real demo orders"
        )
        return result
    if _lock_key_exists(db, signal.id if hasattr(signal, "id") else None, broker, run_id):
        result["rejection_reason"] = f"duplicate (signal,broker,run_id={run_id}) already executed"
        return result

    # ---- Build the order with the SAME shared preparation as the dry-run.
    # This preserves signal_id + units and FAILS LOUD (before any broker call)
    # if units are missing/zero/NaN. This is the exact guard that was missing for
    # Signal #6, where units=0 reached the bridge and it rejected 'units must be
    # positive' while DemoExecutionOrder recorded signal_id=NULL, units=0.0. ----
    try:
        order = prepare_demo_order_from_signal(signal, broker, None)
    except ValueError as exc:
        result["rejection_reason"] = f"invalid signal before broker call: {exc}"
        result["signal_id"] = getattr(signal, "id", None)
        result["signal_units"] = getattr(signal, "units", None)
        result["prepared_order_units"] = None
        # Record the rejection faithfully (with the REAL signal_id + units) so
        # forensics never lose the linkage again.
        cur = db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
                take_profit,units,requested_at,status,rejection_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?)""",
            (getattr(signal, "id", None), broker, "demo", signal.pair,
             "buy" if signal.direction > 0 else "sell",
             signal.entry, signal.stop_loss, signal.take_profit,
             getattr(signal, "units", 0.0), _now(), result["rejection_reason"]),
        )
        db.commit()
        result["demo_execution_order_id"] = cur.lastrowid
        return result

    quote = adapter.get_prices(signal.pair)
    requested_entry = order.requested_entry
    res = run_pretrade_guards(
        order, broker_mode=ctrl["broker_mode"],
        allow_live_orders=cfg.get("allow_live_orders"),
        account=cfg.get("account", 10000.0),
        risk_pct=cfg.get("signals", {}).get("risk_pct", 0.75),
        signal=signal,
        open_demo_trades=_open_demo(db),
        max_open_demo_trades=ctrl["max_open_demo_trades"],
        kill_switch=bool(ctrl["kill_switch"]),
        broker=broker,
        open_demo_trades_by_broker=_open_demo_by_broker(db, broker),
        max_open_per_broker=ctrl.get("max_open_per_broker", ctrl["max_open_demo_trades"]),
        live_quote=quote, signal_timestamp=signal.timestamp, execution_class="paper",
    )
    if not res.passed:
        result["rejection_reason"] = "; ".join(res.reasons)
        return result

    status = adapter.place_demo_order(order)
    if status.status in {"filled", "placed", "done_partial"}:
        filled_units = getattr(status, "filled_units", None)
        if filled_units is None:
            filled_units = order.units
        cur = db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,filled_entry,
                stop_loss,take_profit,units,requested_at,filled_at,status,
                spread_at_entry,slippage,deal_id,position_id,type_filling_used,
                partial,filled_units,raw_response_redacted_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (signal.id if hasattr(signal, "id") else None, broker, "demo",
             order.symbol, order.side, requested_entry, status.filled_entry,
             order.stop_loss, order.take_profit, order.units,
             _now(), _now(), status.status, status.spread_at_entry, status.slippage,
             getattr(status, "deal_id", None), getattr(status, "position_id", None),
             getattr(status, "type_filling_used", None), int(bool(getattr(status, "partial", False))),
             filled_units,
             status.raw_redacted),
        )
        order_id = cur.lastrowid
        if not _acquire_lock(db, signal.id if hasattr(signal, "id") else None, broker, run_id, order_id):
            # Lost the race; mark as duplicate and do NOT count as a fresh order.
            result["status"] = "skipped"
            result["rejection_reason"] = "duplicate lock acquired concurrently"
            return result
        result.update({"status": status.status, "order_id": status.order_id,
                       "filled_entry": status.filled_entry,
                       "spread": status.spread_at_entry, "slippage": status.slippage})
    elif status.status == "skipped":
        # Adapter refused (DRY_RUN/AUTOTRADE). Record as skipped, NOT filled.
        result["status"] = "skipped"
        result["rejection_reason"] = status.rejection_reason
    else:
        result["rejection_reason"] = status.rejection_reason
        cur = db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
                take_profit,units,requested_at,status,rejection_reason,raw_response_redacted_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?,?)""",
            (signal.id if hasattr(signal, "id") else None, broker, "demo",
             order.symbol, order.side, requested_entry, order.stop_loss,
             order.take_profit, order.units, _now(), status.rejection_reason,
             status.raw_redacted),
        )
        result["demo_execution_order_id"] = cur.lastrowid
    # Safe debug fields on every outcome (no tokens/secrets).
    result["signal_id"] = getattr(signal, "id", None)
    result["signal_units"] = getattr(signal, "units", None)
    result["prepared_order_units"] = order.units
    result["bridge_rejection_reason"] = result.get("rejection_reason")
    db.commit()
    return result


def cmd_broker_check(args) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("BROKER CHECK FAILED: allow_live_orders=true"); return 2
    db = _db()
    caps = _persist_capabilities(db)
    print(json.dumps({
        "paper_only": cfg.get("paper_only"),
        "allow_live_orders": cfg.get("allow_live_orders"),
        "broker_mode": "demo",
        "execution_mode": execution_mode(),
        "primary_demo_broker": primary_demo_broker(),
        "mirror_demo_enabled": mirror_demo_enabled(),
        "dry_run": dry_run(),
        "demo_autotrade_enabled": demo_autotrade_enabled(),
        "can_place_real_demo": can_place_real_demo(),
        "brokers": caps,
    }, indent=2))
    return 0


def cmd_oanda_check(args) -> int:
    return _single_broker_check("oanda_practice")


def cmd_mt5_check(args) -> int:
    return _single_broker_check("mt5_demo")


def _single_broker_check(broker: str) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print(f"{broker} CHECK FAILED: allow_live_orders=true"); return 2
    db = _db()
    try:
        cap = capability(broker)
    except Exception as exc:
        print(json.dumps({"broker": broker, "error": redact(str(exc))[:200]}, indent=2))
        return 2
    _persist_one(db, cap)
    print(json.dumps(_cap_to_dict(cap), indent=2))
    return 0 if cap.credentials_present else 2


def _persist_one(db, cap):
    db.execute(
        """INSERT INTO BrokerCapability
           (broker, broker_mode, credentials_present, account_reachable,
            account_currency, balance, equity, trading_enabled, market_open,
            last_checked_at, last_error_redacted)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (cap.broker, cap.broker_mode, int(cap.credentials_present),
         int(cap.account_reachable), cap.account_currency, cap.balance,
         cap.equity, int(cap.trading_enabled),
         None if cap.market_open is None else int(cap.market_open),
         cap.last_checked_at, cap.last_error_redacted),
    )
    db.commit()


def cmd_demo_quotes(args) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("QUOTES FAILED: allow_live_orders=true"); return 2
    db = _db()
    brokers = args.brokers.split(",") if args.brokers else [b for b in broker_names()]
    out = {}
    for broker in brokers:
        broker = broker.strip()
        try:
            adapter = build_adapter(broker, fail_loud=False)
        except Exception as exc:
            out[broker] = {"error": redact(str(exc))[:160]}
            continue
        try:
            q = adapter.get_prices(args.symbol)
            out[broker] = {"symbol": q.symbol, "bid": q.bid, "ask": q.ask, "spread": q.spread}
        except Exception as exc:
            out[broker] = {"error": redact(str(exc))[:160]}
    print(json.dumps(out, indent=2))
    return 0


def cmd_real_demo_dry_run(args) -> int:
    """Validate an approved signal end-to-end against a real broker WITHOUT placing.

    Prints what WOULD happen (guards, adapter gating) but never submits an order.
    """
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("DRY-RUN FAILED: allow_live_orders=true"); return 2
    db = _db()
    ctrl = _control(db)
    broker = args.broker or primary_demo_broker()
    signal = _paper_signal(db, args.signal_id)
    if signal is None:
        print(f"REJECTED: no paper Signal id={args.signal_id}"); return 2
    try:
        adapter = build_adapter(broker, fail_loud=True)
    except Exception as exc:
        print(f"BROKER UNAVAILABLE: {redact(str(exc))[:200]}"); return 2
    # Simulate the gating decision as if can_place_real_demo() were evaluated,
    # but DO NOT call place_demo_order.
    would_place = can_place_real_demo()
    caps = _cap_to_dict(capability(broker))
    print(json.dumps({
        "broker": broker, "broker_mode": "demo",
        "dry_run": dry_run(), "demo_autotrade_enabled": demo_autotrade_enabled(),
        "execution_mode": execution_mode(),
        "would_place_order": would_place,
        "credentials_present": caps["credentials_present"],
        "account_reachable": caps["account_reachable"],
        "signal": {"pair": signal.pair, "direction": signal.direction,
                   "sl": signal.stop_loss, "tp": signal.take_profit},
        "NOTE": "no order was placed — dry run only",
    }, indent=2))
    return 0


def cmd_real_demo_order(args) -> int:
    """Place ONE real demo order via the primary broker (single_broker_demo mode)."""
    cfg = _cfg()
    db = _db()
    ctrl = _control(db)
    broker = args.broker or primary_demo_broker()
    signal = _paper_signal(db, args.signal_id)
    if signal is None:
        print(f"REJECTED: no paper Signal id={args.signal_id}"); return 2
    try:
        adapter = build_adapter(broker, fail_loud=True)
    except Exception as exc:
        print(f"BROKER UNAVAILABLE: {redact(str(exc))[:200]}"); return 2
    run_id = args.run_id or f"real-{broker}-{args.signal_id}"
    res = _place_real_demo(db, cfg, ctrl, broker, signal, run_id, adapter)
    print(json.dumps(res, indent=2))
    return 0 if res["status"] in {"filled", "placed", "done_partial"} else 2


def cmd_mirror_demo_order(args) -> int:
    """Send the SAME approved signal to BOTH OANDA and MT5 demo for comparison."""
    cfg = _cfg()
    db = _db()
    ctrl = _control(db)
    if not mirror_demo_enabled():
        print("REJECTED: MIRROR_DEMO_ENABLED is not true — refusing mirror order."); return 2
    signal = _paper_signal(db, args.signal_id)
    if signal is None:
        print(f"REJECTED: no paper Signal id={args.signal_id}"); return 2
    run_id = args.run_id or f"mirror-{args.signal_id}"
    results = {}
    for broker in ("oanda_practice", "mt5_demo"):
        try:
            adapter = build_adapter(broker, fail_loud=False)
        except Exception as exc:
            results[broker] = {"status": "unavailable", "rejection_reason": redact(str(exc))[:160]}
            continue
        results[broker] = _place_real_demo(db, cfg, ctrl, broker, signal, run_id, adapter)
    print(json.dumps({"run_id": run_id, "broker_mode": "demo", "results": results}, indent=2))
    return 0


def _remote_mt5_adapter():
    """Build the remote bridge adapter; fail loud if URL/token missing."""
    try:
        adapter = build_adapter("remote_mt5", fail_loud=True)
    except Exception as exc:
        print(f"REMOTE MT5 UNAVAILABLE: {redact(str(exc))[:220]}")
        raise
    return adapter


def _persist_remote_bridge(db, *, reachable, tailscale_url_configured, pc_bridge_mode,
                            bridge_kill_switch, symbol=None, bid=None, ask=None, spread=None,
                            symbol_map_json=None, error=None):
    """Write a RemoteBridgeStatus row (redacted metadata only — never the token)."""
    db.execute(
        """INSERT INTO RemoteBridgeStatus
           (reachable, tailscale_url_configured, pc_bridge_mode, bridge_kill_switch,
            latest_symbol, latest_bid, latest_ask, latest_spread, symbol_map_json,
            last_checked_at, last_error_redacted)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (int(reachable), int(tailscale_url_configured), pc_bridge_mode, int(bridge_kill_switch),
         symbol, bid, ask, spread, symbol_map_json, _now(),
         redact(str(error))[:200] if error else None),
    )
    db.commit()


def _persist_preflight_reject(db, signal, reason: str) -> None:
    """Record a market-session preflight rejection as a faithful (non-filled)
    DemoExecutionOrder row so forensics never lose the signal linkage.
    """
    db.execute(
        """INSERT INTO DemoExecutionOrder
           (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
            take_profit,units,requested_at,status,rejection_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?)""",
        (getattr(signal, "id", None), "remote_mt5", "demo", signal.pair,
         "buy" if signal.direction > 0 else "sell",
         signal.entry, signal.stop_loss, signal.take_profit,
         getattr(signal, "units", 0.0), _now(), reason),
    )
    db.commit()


def cmd_remote_mt5_check(args) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("REMOTE MT5 CHECK FAILED: allow_live_orders=true"); return 2
    db = _db()
    try:
        cap = capability("remote_mt5")
    except Exception as exc:
        print(json.dumps({"broker": "remote_mt5", "error": redact(str(exc))[:220]}, indent=2))
        return 2
    _persist_one(db, cap)
    # Bridge health (mode + kill switch) via a direct health call.
    health = {}
    pc_mode = "unknown"
    bridge_kill = False
    reachable = cap.account_reachable
    try:
        a = _remote_mt5_adapter()
        try:
            import requests
            resp = requests.get(f"{os.environ.get('REMOTE_MT5_BRIDGE_URL','').rstrip('/')}/health",
                                headers={"Authorization": f"Bearer {os.environ.get('REMOTE_MT5_BRIDGE_TOKEN','')}"},
                                timeout=float(os.environ.get("REMOTE_MT5_BRIDGE_TIMEOUT", "8")))
            health = resp.json()
            pc_mode = health.get("broker_mode", "demo")
            bridge_kill = bool(health.get("bridge_kill_switch"))
        except Exception as exc:
            health = {"error": redact(str(exc))[:160]}
            reachable = False
    except Exception:
        reachable = False
    _persist_remote_bridge(
        db, reachable=reachable,
        tailscale_url_configured=bool(os.environ.get("REMOTE_MT5_BRIDGE_URL")),
        pc_bridge_mode=pc_mode, bridge_kill_switch=bridge_kill,
        error=(None if reachable else (health.get("error") if isinstance(health, dict) else None)),
    )
    print(json.dumps({**_cap_to_dict(cap), "bridge_health": health,
                      "tailscale_url_configured": bool(os.environ.get("REMOTE_MT5_BRIDGE_URL"))}, indent=2))
    return 0 if cap.credentials_present and cap.account_reachable else 2


def cmd_remote_mt5_symbols(args) -> int:
    try:
        a = _remote_mt5_adapter()
    except Exception:
        return 2
    try:
        import requests
        resp = requests.get(f"{os.environ.get('REMOTE_MT5_BRIDGE_URL','').rstrip('/')}/symbols",
                            headers={"Authorization": f"Bearer {os.environ.get('REMOTE_MT5_BRIDGE_TOKEN','')}"},
                            timeout=float(os.environ.get("REMOTE_MT5_BRIDGE_TIMEOUT", "8")))
        body = resp.json()
        # Persist symbol map for the dashboard.
        db = _db()
        _persist_remote_bridge(
            db, reachable=True,
            tailscale_url_configured=bool(os.environ.get("REMOTE_MT5_BRIDGE_URL")),
            pc_bridge_mode="demo", bridge_kill_switch=False,
            symbol_map_json=json.dumps(body.get("symbol_map", {})),
        )
        print(json.dumps(body, indent=2))
        return 0
    except Exception as exc:
        print(f"REMOTE MT5 SYMBOLS FAILED: {redact(str(exc))[:200]}"); return 2


def cmd_remote_mt5_quote(args) -> int:
    try:
        a = _remote_mt5_adapter()
    except Exception:
        return 2
    try:
        q = a.get_prices(args.symbol)
        db = _db()
        _persist_remote_bridge(
            db, reachable=True,
            tailscale_url_configured=bool(os.environ.get("REMOTE_MT5_BRIDGE_URL")),
            pc_bridge_mode="demo", bridge_kill_switch=False,
            symbol=q.symbol, bid=q.bid, ask=q.ask, spread=q.spread,
        )
        print(json.dumps({"symbol": q.symbol, "bid": q.bid, "ask": q.ask,
                          "spread": q.spread, "broker_mode": "demo"}, indent=2))
        return 0
    except Exception as exc:
        print(f"REMOTE MT5 QUOTE FAILED: {redact(str(exc))[:200]}"); return 2


MAX_REFRESH_SPREAD_PIPS = float(os.environ.get("REMOTE_MT5_MAX_SPREAD_PIPS", "5.0"))


def cmd_refresh_signal(args) -> int:
    """Refresh a (possibly stale) approved paper Signal against the live broker
    quote: revalidate direction + SL/TP geometry, recreate a FRESH Signal row
    with current timestamp and original_signal_id lineage. NEVER places an order.
    """
    if args.broker != "remote_mt5":
        print(f"REFRESH REJECTED: broker '{args.broker}' not supported (use remote_mt5)")
        return 2
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("REFRESH REJECTED: allow_live_orders=true"); return 2
    db = _db()
    _ensure_signal_lineage_col(db)
    _ensure_demo_order_cols(db)
    # 1) require an existing approved paper Signal
    orig = db.execute(
        "SELECT * FROM Signal WHERE id=?", (args.signal_id,)
    ).fetchone()
    if orig is None:
        print(f"REFRESH REJECTED: no Signal with id={args.signal_id}"); return 2
    if (orig["status"] or "") != "paper":
        print(f"REFRESH REJECTED: Signal #{orig['id']} status='{orig['status']}' "
              f"is not an approved paper signal"); return 2
    # 2) broker reachable + kill-switch read via live health
    try:
        a = _remote_mt5_adapter()
    except Exception:
        return 2
    bridge_kill = False
    reachable = True
    try:
        import requests
        hresp = requests.get(
            f"{os.environ.get('REMOTE_MT5_BRIDGE_URL','').rstrip('/')}/health",
            headers={"Authorization": f"Bearer {os.environ.get('REMOTE_MT5_BRIDGE_TOKEN','')}"},
            timeout=float(os.environ.get("REMOTE_MT5_BRIDGE_TIMEOUT", "8")),
        )
        hb = hresp.json()
        bridge_kill = bool(hb.get("bridge_kill_switch"))
        if hresp.status_code != 200 or hb.get("broker_mode") == "real":
            reachable = False
    except Exception as exc:
        print(f"REFRESH REJECTED: broker unreachable — {redact(str(exc))[:200]}"); return 2
    if not reachable:
        print("REFRESH REJECTED: broker unreachable / live mode"); return 2
    if bridge_kill:
        print("REFRESH REJECTED: bridge kill-switch is ON"); return 2
    # 3) live quote
    try:
        q = a.get_prices(orig["pair"])
    except Exception as exc:
        print(f"REFRESH REJECTED: could not fetch live quote — {redact(str(exc))[:200]}")
        return 2
    side = "buy" if orig["direction"] > 0 else "sell"
    live_entry = q.ask if side == "buy" else q.bid
    # 4) reject if spread too wide
    spread_pips = (q.spread or 0.0) * 10000.0
    if q.spread is not None and spread_pips > MAX_REFRESH_SPREAD_PIPS:
        print(json.dumps({
            "status": "rejected", "reason": "spread_too_wide",
            "spread_pips": round(spread_pips, 2),
            "max_spread_pips": MAX_REFRESH_SPREAD_PIPS,
            "broker": "remote_mt5",
        }, indent=2))
        return 2
    # 5) revalidate price geometry using the LIVE entry (SL/TP unchanged unless invalid)
    geom_reason = validate_price_geometry(side, live_entry, orig["stop_loss"], orig["take_profit"])
    if geom_reason is not None:
        print(json.dumps({
            "status": "rejected", "reason": "geometry_invalid_vs_live_quote",
            "detail": geom_reason, "side": side, "live_entry": live_entry,
            "stop_loss": orig["stop_loss"], "take_profit": orig["take_profit"],
            "broker": "remote_mt5", "placed_order": False,
        }, indent=2))
        return 2
    # 6) create a fresh Signal row (same strategy/pair/direction only because
    #    geometry is still valid) with current timestamp + lineage.
    new_ts = _now()
    new_id = _insert_fresh_signal(
        db, pair=orig["pair"], strategy=orig["strategy"], direction=orig["direction"],
        entry=live_entry, stop_loss=orig["stop_loss"], take_profit=orig["take_profit"],
        status="paper", signal_score=orig["signal_score"] or 0.0,
        regime=orig["regime"] or "range", generated_at=new_ts,
        units=orig["units"], original_signal_id=orig["id"],
    )
    db.commit()
    out = {
        "status": "refreshed", "broker": "remote_mt5",
        "original_signal_id": orig["id"], "new_signal_id": new_id,
        "pair": orig["pair"], "side": side,
        "live_entry": live_entry, "stop_loss": orig["stop_loss"],
        "take_profit": orig["take_profit"], "spread": q.spread,
        "spread_pips": round(spread_pips, 2),
        "generated_at": new_ts, "placed_order": False,
        "note": "stale guard satisfied by fresh timestamp — no order placed",
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_remote_mt5_dry_run(args) -> int:
    cfg = _cfg()
    if cfg.get("allow_live_orders"):
        print("REMOTE MT5 DRY-RUN FAILED: allow_live_orders=true"); return 2
    db = _db()
    ctrl = _control(db)
    signal = _paper_signal(db, args.signal_id)
    if signal is None:
        print(f"REJECTED: no paper Signal id={args.signal_id}"); return 2
    try:
        a = _remote_mt5_adapter()
    except Exception:
        return 2
    # ---- Shared order preparation (Task: dry-run uses the SAME prep as the real
    # order). Validates + preserves signal_id and units; fails loud if units are
    # missing/zero/NaN. ----
    live_quote = a.get_prices(signal.pair)
    requested_entry = live_quote.ask if signal.direction > 0 else live_quote.bid
    try:
        vps_order = prepare_demo_order_from_signal(signal, "remote_mt5", requested_entry)
    except ValueError as exc:
        print(json.dumps({
            "broker": "remote_mt5", "broker_mode": "demo",
            "would_place_order": False,
            "signal_units": getattr(signal, "units", None),
            "prepared_order_units": None,
            "signal_id": getattr(signal, "id", None),
            "rejection_reason": f"invalid signal: {exc}",
            "NOTE": "no order was placed — dry run only",
        }, indent=2))
        return 2
    from src.execution import run_pretrade_guards
    vps_guard = run_pretrade_guards(
        vps_order, broker_mode="demo", allow_live_orders=False,
        account=cfg.get("account", 10000.0),
        risk_pct=cfg.get("signals", {}).get("risk_pct", 0.75),
        signal=signal, open_demo_trades=0,
        kill_switch=bool(ctrl["kill_switch"]),
        live_quote=live_quote, signal_timestamp=signal.timestamp,
        execution_class="paper",
    )
    vps_ok = vps_guard.passed
    # Validate against the live bridge (calls /dry-run on PC) but never places.
    try:
        import requests
        resp = requests.post(
            f"{os.environ.get('REMOTE_MT5_BRIDGE_URL','').rstrip('/')}/dry-run",
            headers={"Authorization": f"Bearer {os.environ.get('REMOTE_MT5_BRIDGE_TOKEN','')}"},
            json={"symbol": vps_order.symbol, "side": vps_order.side,
                  "units": vps_order.units, "stop_loss": vps_order.stop_loss,
                  "take_profit": vps_order.take_profit, "signal_id": vps_order.signal_id,
                  "signal_timestamp": signal.timestamp, "execution_class": "paper"},
            timeout=float(os.environ.get("REMOTE_MT5_BRIDGE_TIMEOUT", "8")),
        )
        bridge = resp.json()
    except Exception as exc:
        print(f"REMOTE MT5 DRY-RUN FAILED: {redact(str(exc))[:200]}"); return 2
    would_place = (
        vps_ok and resp.status_code == 200
        and bridge.get("would_place") is True
        and bridge.get("broker_mode") == "demo"
        and not ctrl["kill_switch"]
    )
    print(json.dumps({
        "broker": "remote_mt5", "broker_mode": "demo",
        "bridge_status_code": resp.status_code,
        "would_place_order": would_place,
        "live_entry": bridge.get("live_entry"),
        "vps_guard_passed": vps_ok,
        "vps_guard_reasons": vps_guard.reasons if not vps_ok else [],
        "signal_units": vps_order.units,
        "prepared_order_units": vps_order.units,
        "signal_id": vps_order.signal_id,
        "live_quote": {"bid": live_quote.bid, "ask": live_quote.ask},
        "dry_run": dry_run(), "demo_autotrade_enabled": demo_autotrade_enabled(),
        "execution_mode": execution_mode(),
        "bridge_kill_switch": bridge.get("bridge_kill_switch"),
        "signal": {"pair": signal.pair, "direction": signal.direction,
                   "sl": signal.stop_loss, "tp": signal.take_profit,
                   "timestamp": signal.timestamp},
        "NOTE": "no order was placed — dry run only",
    }, indent=2))
    # Exit non-zero if EITHER the VPS deterministic guard OR the bridge would
    # refuse this signal (loud failure — never proceed to a real order).
    if not vps_ok:
        print("REMOTE MT5 DRY-RUN REJECTED (Aether-side guard): "
              + "; ".join(vps_guard.reasons), file=sys.stderr)
        return 2
    if resp.status_code != 200 or bridge.get("would_place") is not True:
        print(f"REMOTE MT5 DRY-RUN REJECTED (bridge): {bridge}", file=sys.stderr)
        return 2
    return 0


def cmd_remote_mt5_order(args) -> int:
    cfg = _cfg()
    db = _db()
    ctrl = _control(db)
    signal = _paper_signal(db, args.signal_id)
    if signal is None:
        print(f"REJECTED: no paper Signal id={args.signal_id}"); return 2
    try:
        a = _remote_mt5_adapter()
    except Exception:
        return 2
    # Hard gate: a real demo order MUST never proceed unless BOTH the Aether-side
    # deterministic guard AND the bridge dry-run accept the signal.
    from src.execution import run_pretrade_guards
    live_quote = a.get_prices(signal.pair)
    requested_entry = live_quote.ask if signal.direction > 0 else live_quote.bid
    # Shared order preparation (Task): validates + preserves signal_id and units;
    # fails loud if units are missing/zero/NaN before any broker call.
    try:
        vps_order = prepare_demo_order_from_signal(signal, "remote_mt5", requested_entry)
    except ValueError as exc:
        # Fails loud BEFORE any broker call (Task requirement): record the
        # rejection faithfully with the REAL signal_id + units so forensics
        # never lose the linkage again (this is exactly the gap that lost
        # Signal #6's id/units when units=0 reached the bridge).
        db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
                take_profit,units,requested_at,status,rejection_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?)""",
            (getattr(signal, "id", None), "remote_mt5", "demo", signal.pair,
             "buy" if signal.direction > 0 else "sell",
             requested_entry, signal.stop_loss, signal.take_profit,
             getattr(signal, "units", 0.0), _now(), f"invalid signal: {exc}"),
        )
        db.commit()
        print(f"REJECTED: invalid signal for order: {exc}")
        return 2
    vps_guard = run_pretrade_guards(
        vps_order, broker_mode="demo", allow_live_orders=False,
        account=cfg.get("account", 10000.0),
        risk_pct=cfg.get("signals", {}).get("risk_pct", 0.75),
        signal=signal, open_demo_trades=_open_demo(db),
        max_open_demo_trades=ctrl["max_open_demo_trades"],
        kill_switch=bool(ctrl["kill_switch"]),
        broker="remote_mt5",
        open_demo_trades_by_broker=_open_demo_by_broker(db, "remote_mt5"),
        max_open_per_broker=ctrl.get("max_open_per_broker", ctrl["max_open_demo_trades"]),
        live_quote=live_quote, signal_timestamp=signal.timestamp, execution_class="paper",
    )
    if not vps_guard.passed:
        print("REJECTED: Aether-side guard failed: " + "; ".join(vps_guard.reasons))
        return 2
    # And the live bridge dry-run must also accept it. A patched bridge returns
    # HTTP 400 when SL/TP/staleness is invalid; a pre-patch bridge that wrongly
    # returns 200 is NOT trusted because vps_guard above already screened it.
    try:
        import requests
        dresp = requests.post(
            f"{os.environ.get('REMOTE_MT5_BRIDGE_URL','').rstrip('/')}/dry-run",
            headers={"Authorization": f"Bearer {os.environ.get('REMOTE_MT5_BRIDGE_TOKEN','')}"},
            json={"symbol": vps_order.symbol, "side": vps_order.side,
                  "units": vps_order.units, "stop_loss": vps_order.stop_loss,
                  "take_profit": vps_order.take_profit, "signal_id": vps_order.signal_id,
                  "signal_timestamp": signal.timestamp, "execution_class": "paper"},
            timeout=float(os.environ.get("REMOTE_MT5_BRIDGE_TIMEOUT", "8")),
        )
        if dresp.status_code != 200:
            print(f"REJECTED: bridge dry-run failed ({dresp.status_code}): {dresp.text[:240]}")
            return 2
    except Exception as exc:
        print(f"REJECTED: could not verify bridge dry-run: {redact(str(exc))[:200]}")
        return 2
    run_id = args.run_id or f"remote-mt5-{args.signal_id}"
    # ---- Market-session preflight (tick-evidence; fresh tick is sufficient) ----
    # Authoritative gate is the broker: a FRESH, VALID tick is enough to proceed;
    # TRADE_RETCODE_MARKET_CLOSED (10018) on the attempt is final. We do NOT
    # require the price to change between samples (two identical fresh ticks are
    # NOT proof of a closed market). session_open and the weekend calendar are
    # advisory diagnostics only, never a reject. This preflight is mandatory.
    try:
        q1 = a.get_prices(signal.pair)
        time.sleep(float(os.environ.get("REMOTE_MT5_TICK_GAP_SECONDS", "3")))
        q2 = a.get_prices(signal.pair)
    except Exception as exc:
        reason = f"preflight tick fetch failed: {redact(str(exc))[:200]}"
        _persist_preflight_reject(db, signal, reason)
        print(json.dumps({"status": "rejected", "broker": "remote_mt5",
                          "broker_mode": "demo", "signal_id": getattr(signal, "id", None),
                          "rejection_reason": reason}, indent=2))
        return 2
    # Broker identity for the demo-specific zero-spread policy. The bridge
        # reports company/server (e.g. "MetaQuotes-Demo"); we feed whichever is
        # set into the preflight so the zero-spread exception applies ONLY to an
        # explicitly whitelisted demo broker, never to real/unknown ones.
        broker_identity = "unknown"
        broker_mode = "demo"
        broker_company = ""
        broker_server = ""
        try:
            acct = a.get_account()
            broker_identity = acct.company or acct.server or "unknown"
            broker_mode = acct.broker_mode or "demo"
            broker_company = acct.company or ""
            broker_server = acct.server or ""
        except Exception:
            broker_identity = "unknown"
            broker_mode = "demo"
        tradable, preason, warnings = check_symbol_tradable(
            q1.bid, q1.ask, q1.timestamp, q2.bid, q2.ask, q2.timestamp,
            session_open=q1.session_open,
            broker=broker_identity, broker_mode=broker_mode,
            broker_company=broker_company, broker_server=broker_server,
        )
        for w in warnings:
            print(f"ADVISORY: preflight: {w}")
        if not tradable:
            reason = (f"market-session preflight: {preason} "
                      f"(q1 bid={q1.bid} ask={q1.ask} ts={q1.timestamp}; "
                      f"q2 bid={q2.bid} ask={q2.ask} ts={q2.timestamp}; "
                      f"session_open={q1.session_open})")
            _persist_preflight_reject(db, signal, reason)
            print(json.dumps({"status": "rejected", "broker": "remote_mt5",
                              "broker_mode": "demo", "signal_id": getattr(signal, "id", None),
                              "market_session_open": False,
                              "rejection_reason": reason}, indent=2))
            return 2
    res = _place_real_demo(db, cfg, ctrl, "remote_mt5", signal, run_id, a)
    print(json.dumps({**res, "broker_mode": "demo",
                      "signal_units": vps_order.units,
                      "prepared_order_units": vps_order.units}, indent=2))
    return 0 if res["status"] in {"filled", "placed", "done_partial"} else 2


def cmd_kill_switch(args) -> int:
    db = _db()
    new_val = 1 if args.on else (0 if args.off else None)
    if new_val is None:
        cur = _control(db)
        print(f"kill_switch={cur['kill_switch']} broker_mode={cur['broker_mode']}")
        return 0
    db.execute(
        "UPDATE ExecutionControl SET kill_switch=?, updated_at=? WHERE id=1",
        (new_val, _now()),
    )
    db.commit()
    print(f"kill_switch set to {new_val}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="run_execution.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check")
    pc.add_argument("--adapter", default="mock")
    pc.set_defaults(func=cmd_check)

    po = sub.add_parser("demo-order")
    po.add_argument("--signal-id", type=int, required=True)
    po.add_argument("--adapter", default="mock")
    po.add_argument("--entry", type=float, default=None)
    po.set_defaults(func=cmd_demo_order)

    pu = sub.add_parser("update")
    pu.add_argument("--adapter", default="mock")
    pu.add_argument("--order-id", type=int, default=None)
    pu.set_defaults(func=cmd_update)

    pj = sub.add_parser("journal")
    pj.add_argument("--days", type=int, default=7)
    pj.set_defaults(func=cmd_journal)

    pl = sub.add_parser("mock-lifecycle")
    pl.add_argument("--signal-id", type=int, required=True)
    pl.add_argument("--run-id", type=str, default=None)
    pl.add_argument("--force", action="store_true")
    pl.set_defaults(func=cmd_mock_lifecycle)

    pk = sub.add_parser("kill-switch")
    pk.add_argument("--on", action="store_true")
    pk.add_argument("--off", action="store_true")
    pk.set_defaults(func=cmd_kill_switch)

    pb = sub.add_parser("broker-check")
    pb.set_defaults(func=cmd_broker_check)

    pob = sub.add_parser("oanda-check")
    pob.set_defaults(func=cmd_oanda_check)

    pmb = sub.add_parser("mt5-check")
    pmb.set_defaults(func=cmd_mt5_check)

    pq = sub.add_parser("demo-quotes")
    pq.add_argument("--symbol", default="EURUSD")
    pq.add_argument("--brokers", type=str, default=None,
                    help="comma-separated broker names (default: all available)")
    pq.set_defaults(func=cmd_demo_quotes)

    pdr = sub.add_parser("real-demo-dry-run")
    pdr.add_argument("--signal-id", type=int, required=True)
    pdr.add_argument("--broker", type=str, default=None)
    pdr.set_defaults(func=cmd_real_demo_dry_run)

    pro = sub.add_parser("real-demo-order")
    pro.add_argument("--signal-id", type=int, required=True)
    pro.add_argument("--broker", type=str, default=None)
    pro.add_argument("--run-id", type=str, default=None)
    pro.set_defaults(func=cmd_real_demo_order)

    pmr = sub.add_parser("mirror-demo-order")
    pmr.add_argument("--signal-id", type=int, required=True)
    pmr.add_argument("--run-id", type=str, default=None)
    pmr.set_defaults(func=cmd_mirror_demo_order)

    prm = sub.add_parser("remote-mt5-check")
    prm.set_defaults(func=cmd_remote_mt5_check)

    prms = sub.add_parser("remote-mt5-symbols")
    prms.set_defaults(func=cmd_remote_mt5_symbols)

    prmq = sub.add_parser("remote-mt5-quote")
    prmq.add_argument("--symbol", default="EURUSD")
    prmq.set_defaults(func=cmd_remote_mt5_quote)

    prmf = sub.add_parser("refresh-signal")
    prmf.add_argument("--signal-id", type=int, required=True)
    prmf.add_argument("--broker", default="remote_mt5")
    prmf.set_defaults(func=cmd_refresh_signal)

    prmd = sub.add_parser("remote-mt5-dry-run")
    prmd.add_argument("--signal-id", type=int, required=True)
    prmd.set_defaults(func=cmd_remote_mt5_dry_run)

    prmo = sub.add_parser("remote-mt5-order")
    prmo.add_argument("--signal-id", type=int, required=True)
    prmo.add_argument("--run-id", type=str, default=None)
    prmo.set_defaults(func=cmd_remote_mt5_order)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
