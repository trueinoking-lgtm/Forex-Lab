#!/usr/bin/env python
"""run_trends.py — Market Trend Intelligence detection + prediction emission.

For each enabled forex/metal symbol it:
  1. loads price history (cached yfinance; raises on missing — never fake data)
  2. builds a probabilistic regime + direction snapshot (src/trend.py)
  3. emits one prediction per horizon (1h/4h/1d) with a required invalidation
     price and an evidence-based confidence

Output: writes engine/results/trends.json (read by app/scripts/trend_ingest.mjs
which loads it into SQLite: MarketTrendSnapshot + TrendPrediction).

SAFETY:
  - Respects paper_only; this module NEVER places or sizes an order.
  - No certainty language: outputs are probabilities + invalidations.
  - If paper_only is false or live orders allowed, it refuses entirely.
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path
import yaml
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from src import data, trend, log

CFG = yaml.safe_load(open("config.yaml"))

import numpy as np


def _ema(price: pd.Series, span: int) -> pd.Series:
    return price.ewm(span=span, adjust=False).mean()


# canonical Market symbol -> yfinance ticker
YFIN_MAP = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X", "USDCHF": "USDCHF=X", "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X", "XAUUSD": "GC=F",
}
HORIZONS = ["1h", "4h", "1d"]


def load_history(db_path: str, asset_class: str) -> dict | None:
    """Strategy history in a similar regime, from the lab's scored backtests.

    Returns {strategy, win_rate, robustness, sample} for the best-scored
    strategy in the same asset class, or None if no history exists.
    """
    try:
        import sqlite3
        con = sqlite3.connect(db_path)
        row = con.execute(
            """SELECT s.strategy, AVG(r.score), AVG(s.win_rate), AVG(r.robustness),
                      COUNT(*) FROM BacktestRun s JOIN StrategyScore r ON r.run_id=s.id
               WHERE s.asset_class=? GROUP BY s.strategy ORDER BY AVG(r.score) DESC LIMIT 1""",
            (asset_class,)).fetchone()
        con.close()
        if not row or row[4] is None or row[4] < 1:
            return None
        return {"strategy": row[0], "win_rate": float(row[2] or 0.0),
                "robustness": float(row[3] or 0.0), "sample": int(row[4])}
    except Exception as e:  # pragma: no cover - DB optional
        log.log(f"[trends] history lookup skipped: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="path to app/forex_lab.db")
    args = ap.parse_args()

    if not CFG.get("paper_only") or CFG.get("allow_live_orders"):
        raise SystemExit("[SAFETY] paper_only must be true and allow_live_orders false. Refusing.")

    d = CFG["data"]
    db_path = args.db or str(Path(__file__).parent.parent / "app" / "forex_lab.db")

    # enabled forex/metal symbols (skip disabled crypto by design)
    symbols = [s for s, ac, en in MARKETS if en and ac in ("forex", "metal")]
    if not symbols:
        symbols = ["EURUSD"]  # fallback so the loop is never empty in a clean repo

    out = {"generated_at": str(pd.Timestamp.now(tz="UTC")), "timeframe": d["timeframe"],
           "snapshots": [], "predictions": []}
    now = pd.Timestamp.now(tz="UTC")

    for sym in symbols:
        ticker = YFIN_MAP.get(sym, f"{sym}=X")
        try:
            df = data.load_pair(ticker, d["source"], timeframe=d["timeframe"],
                                lookback_days=d["lookback_days"], cache_dir=d["cache_dir"])
        except Exception as e:
            log.log(f"[trends] skip {sym} ({ticker}): {e}")
            continue
        close, high, low = df["close"].astype(float), df["high"].astype(float), df["low"].astype(float)
        asset_class = next((ac for s, ac, en in MARKETS if s == sym), "forex")
        hist = load_history(db_path, asset_class)

        snap = trend.build_snapshot(close, high, low, sym, d["timeframe"], history=hist)
        snap["detected_at"] = str(now)
        out["snapshots"].append(snap)
        log.log(f"[trends] {sym}: regime={snap['regime']} dir={snap['direction']} "
                f"conf={snap['confidence_score']:.2f} inv={snap['invalidation_price']}")

        # emit one prediction per horizon
        ef = _ema(close, 12)
        ema_slope_sign = int(np.sign(ef.iloc[-1] - ef.iloc[-2]))
        prev_close = float(close.iloc[-2])
        for h in HORIZONS:
            entry_ctx = {
                "entry_price": round(float(close.iloc[-1]), 5),
                "prev_close": round(prev_close, 5),
                "ema_slope_sign": ema_slope_sign,
                "probabilities": snap["probabilities"],
                "regime": snap["regime"],
                "note": "evidence-based, probabilistic; not a trade instruction",
            }
            out["predictions"].append({
                "symbol": sym, "timeframe": d["timeframe"],
                "prediction_time": str(now), "horizon": h,
                "predicted_direction": snap["direction"],
                "confidence_score": snap["confidence_score"],
                "entry_context_json": json.dumps(entry_ctx),
                "invalidation_price": snap["invalidation_price"],
            })

    Path("results").mkdir(exist_ok=True)
    path = Path("results/trends.json")
    path.write_text(json.dumps(out, indent=2))
    log.log(f"[trends] wrote {path} ({len(out['snapshots'])} snapshots, "
            f"{len(out['predictions'])} predictions)")


# markets pulled from the app DB at runtime (enabled forex/metal)
def _load_markets(db_path: str):
    try:
        import sqlite3
        con = sqlite3.connect(db_path)
        rows = con.execute("SELECT symbol, asset_class, enabled FROM Market").fetchall()
        con.close()
        return [(r[0], r[1], bool(r[2])) for r in rows]
    except Exception:
        return [("EURUSD", "forex", True)]


MARKETS = _load_markets(str(Path(__file__).parent.parent / "app" / "forex_lab.db"))


if __name__ == "__main__":
    main()
