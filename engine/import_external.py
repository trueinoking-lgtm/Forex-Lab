#!/usr/bin/env python
"""import_external.py — import external research results, re-score to OUR rules.

Usage:
  python import_external.py <file.json|file.csv> [--spread-bps N] [--slippage-bps N]

Reads the import file, validates each row (fail-loud on bad/fake data), labels
it is_external=True, then RE-SCORES every strategy with OUR spread/slippage/
walk-forward/paper rules. Writes results/imports.json for the Next.js loader.

SAFETY: paper_only. No order placement. No broker credentials. External
platforms are idea sources only; this lab is the source of truth.
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src import imports, markets as M, log

CFG = None
try:
    import yaml
    CFG = yaml.safe_load(open("config.yaml"))
except Exception:
    CFG = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--spread-bps", type=float, default=None)
    ap.add_argument("--slippage-bps", type=float, default=None)
    args = ap.parse_args()

    if CFG and (not CFG.get("paper_only") or CFG.get("allow_live_orders")):
        raise SystemExit("[SAFETY] paper_only must be true — refusing external import.")

    results = imports.parse_file(args.file)
    re_scored = []
    for r in results:
        sc = imports.re_score(r, override_spread_bps=args.spread_bps,
                              override_slippage_bps=args.slippage_bps)
        re_scored.append(sc)
        log.log(f"[import] {r.source:11s} {r.strategy_name:24s} {r.symbol:7s} "
                f"ext_ret={r.net_return:+.3f} -> re-scored score={sc['score']} "
                f"(our_cost={sc['our_cost_bps']}bps gap={sc['cost_gap_bps']}bps)")

    # cross-market summary
    by_class = {}
    for sc in re_scored:
        by_class.setdefault(sc["asset_class"] or "unknown", []).append(sc)
    matrix = {k: sorted(v, key=lambda x: x["score"], reverse=True)[:5] for k, v in by_class.items()}

    out = {
        "generated_at": str(__import__("pandas").Timestamp.now(tz="UTC")),
        "source_file": args.file,
        "count": len(re_scored),
        "is_external": True,
        "paper_only": True,
        "results": re_scored,
        "cross_market_matrix": matrix,
    }
    Path("results").mkdir(exist_ok=True)
    Path("results/imports.json").write_text(json.dumps(out, indent=2, default=str))
    log.log(f"[import] wrote results/imports.json ({len(re_scored)} strategies re-scored)")
    log.log(f"[import] markets available: {', '.join(M.universe_symbols())}")


if __name__ == "__main__":
    main()
