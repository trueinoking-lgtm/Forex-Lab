#!/usr/bin/env python3
"""Register one already-computed backtest result (research only)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from src.experiment_registry import file_sha256, git_commit, register_experiment
from src.accounting import accounting_metadata
from strategies.registry import REGISTRY


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", required=True, type=Path)
    parser.add_argument("--strategy", required=True, choices=sorted(REGISTRY))
    parser.add_argument("--data-artifact", type=Path)
    parser.add_argument("--date-start")
    parser.add_argument("--date-end")
    parser.add_argument("--train-boundary")
    parser.add_argument("--validation-boundary")
    parser.add_argument("--oos-boundary")
    parser.add_argument("--random-seed", type=int)
    parser.add_argument("--store", type=Path, default=BASE / "results" / "experiment_registry.json")
    parser.add_argument("--markdown", type=Path, default=BASE / "results" / "experiment_registry.md")
    args = parser.parse_args()

    cfg = yaml.safe_load((BASE / "config.yaml").read_text())
    if not cfg.get("paper_only") or cfg.get("allow_live_orders"):
        raise SystemExit("[SAFETY] registry requires paper_only=true and allow_live_orders=false")
    result_doc = json.loads(args.backtest.read_text())
    try:
        result = next(row for row in result_doc["results"] if row["strategy"] == args.strategy)
    except (KeyError, StopIteration) as exc:
        raise SystemExit(f"strategy {args.strategy!r} is absent from {args.backtest}") from exc
    _, params = REGISTRY[args.strategy]
    costs = cfg["cost"]
    payload = {
        **accounting_metadata(has_explicit_stop=False),
        "git_commit_hash": git_commit(BASE.parent),
        "strategy_name": args.strategy,
        "strategy_parameters": params,
        "symbol": result_doc.get("pair", cfg["data"]["symbol"]),
        "timeframe": result_doc.get("timeframe", cfg["data"]["timeframe"]),
        "data_source": cfg["data"]["source"],
        "data_fingerprint": file_sha256(args.data_artifact) if args.data_artifact else None,
        "date_range": {"start": args.date_start, "end": args.date_end},
        "boundaries": {"train": args.train_boundary, "validation": args.validation_boundary,
                       "oos": args.oos_boundary},
        "spread_bps": costs["spread_bps"],
        "slippage_bps": costs["slippage_bps"],
        "commission_bps": costs["fee_bps"],
        "random_seed": args.random_seed,
        "trade_count": result.get("trade_count"),
        "performance_metrics": result,
        "artifact_paths": [str(args.backtest)] + ([str(args.data_artifact)] if args.data_artifact else []),
    }
    record = register_experiment(payload, args.store, args.markdown)
    print(record["experiment_id"])


if __name__ == "__main__":
    main()
