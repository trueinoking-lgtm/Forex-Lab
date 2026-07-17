#!/usr/bin/env python
"""Run the close-only paper simulator. No broker/order path is imported."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import yaml

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
from src import data, log  # noqa: E402
from src.paper_sim import simulate  # noqa: E402

CFG = yaml.safe_load((ENGINE_DIR / "config.yaml").read_text())


def _normalize(row: dict) -> dict:
    direction = int(row.get("direction", 0) or 0)
    return {"symbol": row.get("pair"), "side": "buy" if direction > 0 else "sell",
            "entry": row.get("entry"), "stop_loss": row.get("stop_loss"),
            "take_profit": row.get("take_profit"), "units": row.get("units"),
            "timestamp": row.get("generated_at", row.get("timestamp")), "tradeable": True}


def load_approved_signals(db_path: Path, pair: str) -> list[dict]:
    """Prefer approved/paper DB signals, then the engine's generated signal JSON."""
    if db_path.exists():
        try:
            con = sqlite3.connect(str(db_path))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM Signal WHERE pair IN (?, ?) AND status='paper' ORDER BY generated_at",
                (pair, pair.replace("=X", "")),
            ).fetchall()
            con.close()
            if rows:
                return [_normalize(dict(row)) for row in rows]
        except sqlite3.Error as exc:
            log.log(f"[paper-sim] DB signal lookup skipped: {exc}")
    path = ENGINE_DIR / "results" / f"signals_{pair.replace('/', '')}.json"
    if path.exists():
        payload = json.loads(path.read_text())
        return [{**_normalize(s), "tradeable": s.get("tradeable", True)}
                for s in payload.get("signals", [])]
    return []


def demo_signals(price: pd.Series, pair: str) -> list[dict]:
    """Explicitly labelled momentum examples used only when no approvals exist."""
    if len(price) < 8:
        return []
    signals = []
    for pos in range(3, len(price) - 1, max(5, len(price) // 8)):
        entry = float(price.iloc[pos])
        direction = 1 if price.iloc[pos] >= price.iloc[pos - 3] else -1
        distance = max(abs(entry) * 0.005, 1e-6)
        signals.append({"symbol": pair, "side": "buy" if direction > 0 else "sell",
                        "entry": entry, "stop_loss": entry - direction * distance,
                        "take_profit": entry + direction * distance * 1.5,
                        "units": 0, "timestamp": str(price.index[pos]),
                        "tradeable": True, "is_demo": True})
    return signals


def _json_safe(value):
    """Represent non-finite ratios explicitly while keeping standards-compliant JSON."""
    if isinstance(value, float) and not pd.notna(value):
        return None
    if isinstance(value, float) and value == float("inf"):
        return "Infinity"
    if isinstance(value, float) and value == float("-inf"):
        return "-Infinity"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="EURUSD=X")
    parser.add_argument("--db", default="forex_lab.db")
    args = parser.parse_args()
    if not CFG.get("paper_only") or CFG.get("allow_live_orders"):
        raise SystemExit("[SAFETY] paper_only must be true and allow_live_orders false. Refusing.")

    cfg_data = CFG["data"]
    frame = data.load_pair(args.pair, cfg_data["source"], timeframe=cfg_data["timeframe"],
                           lookback_days=cfg_data["lookback_days"],
                           cache_dir=str(ENGINE_DIR / cfg_data["cache_dir"]))
    price = frame["close"].astype(float)
    signals = load_approved_signals(Path(args.db), args.pair)
    demo = not signals
    if demo:
        signals = demo_signals(price, args.pair)
        log.log("[paper-sim] no approved signals found; using labelled demo momentum signals")
    cost = CFG["cost"]
    result = simulate(signals, price, cost["fee_bps"] + cost["slippage_bps"] + cost["spread_bps"],
                      CFG["backtest"]["initial_capital"], CFG["signals"]["risk_pct"])
    result.update({"generated_at": str(pd.Timestamp.now(tz="UTC")), "pair": args.pair,
                   "demo_signals": demo, "safety_note": "paper only, no orders placed"})
    out_dir = ENGINE_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"paper_sim_{args.pair.replace('/', '')}.json"
    path.write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False))
    for trade in result["trades"]:
        log.log(f"[paper-sim] {trade['side']} {trade['units']:.2f} "
                f"{trade['entry']:.5f}->{trade['exit']:.5f} pnl={trade['pnl']:+.2f} {trade['reason']}")
    log.log(f"[paper-sim] wrote {path} ({len(result['trades'])} paper trades)")


if __name__ == "__main__":
    main()
