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
from datetime import datetime, timezone

import yaml  # noqa: E402

# allow running from engine/ dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.signals import PaperSignal  # noqa: E402
from src.execution import (  # noqa: E402
    build_adapter, run_pretrade_guards, GuardError, redact, MockDemoAdapter,
    DemoOrderRequest,
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
    return db


def _control(db: sqlite3.Connection) -> dict:
    row = db.execute("SELECT * FROM ExecutionControl WHERE id=1").fetchone()
    return dict(row) if row else {"kill_switch": 0, "broker_mode": "demo",
                                  "max_open_demo_trades": 5}


def _open_demo(db: sqlite3.Connection) -> int:
    return db.execute(
        "SELECT COUNT(*) c FROM DemoExecutionOrder WHERE status='filled'"
    ).fetchone()["c"]


def _paper_signal(db: sqlite3.Connection, signal_id: int) -> PaperSignal | None:
    row = db.execute("SELECT * FROM Signal WHERE id=?", (signal_id,)).fetchone()
    if not row:
        return None
    return PaperSignal(
        pair=row["pair"], strategy=row["strategy"], direction=row["direction"],
        entry=row["entry"], stop_loss=row["stop_loss"], take_profit=row["take_profit"],
        signal_score=row["signal_score"] or 0.0, regime=row["regime"] or "range",
        timestamp=row["generated_at"],
    )


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
        requested_entry=requested_entry,
    )
    res = run_pretrade_guards(
        order, broker_mode=ctrl["broker_mode"], allow_live_orders=cfg.get("allow_live_orders"),
        account=cfg.get("account", 10000.0), risk_pct=cfg.get("signals", {}).get("risk_pct", 0.75),
        signal=signal, open_demo_trades=_open_demo(db),
        max_open_demo_trades=ctrl["max_open_demo_trades"], kill_switch=bool(ctrl["kill_switch"]),
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
    if status.status == "filled":
        db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,filled_entry,
                stop_loss,take_profit,units,requested_at,filled_at,status,
                spread_at_entry,slippage,raw_response_redacted_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (args.signal_id, adapter.name, "demo", order.symbol, order.side, requested_entry,
             status.filled_entry, order.stop_loss, order.take_profit, order.units,
             _now(), _now(), "filled", status.spread_at_entry, status.slippage,
             status.raw_redacted),
        )
    else:
        db.execute(
            """INSERT INTO DemoExecutionOrder
               (signal_id,broker,broker_mode,symbol,side,requested_entry,stop_loss,
                take_profit,units,requested_at,status,rejection_reason,raw_response_redacted_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,'rejected',?,?)""",
            (args.signal_id, adapter.name, "demo", order.symbol, order.side, requested_entry,
             order.stop_loss, order.take_profit, order.units, _now(), status.rejection_reason,
             status.raw_redacted),
        )
    db.commit()
    print(json.dumps({
        "status": status.status, "order_id": status.order_id,
        "filled_entry": status.filled_entry, "spread": status.spread_at_entry,
        "slippage": status.slippage, "risk": res.risk,
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

    pk = sub.add_parser("kill-switch")
    pk.add_argument("--on", action="store_true")
    pk.add_argument("--off", action="store_true")
    pk.set_defaults(func=cmd_kill_switch)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
