#!/usr/bin/env python
"""Reproduce deterministic research baselines (never submits orders)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from src import baseline, data  # noqa: E402
from strategies.registry import REGISTRY  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--data-file", help="explicit OHLCV CSV (useful for an audited cache)")
    args = parser.parse_args()

    with (ENGINE_DIR / "config.yaml").open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    data_config = config["data"]
    symbol = args.pair or data_config["symbol"]
    costs = config["cost"]
    backtest_config = config["backtest"]
    context = {
        "walk_forward": backtest_config["walk_forward"],
        "cost_bps": costs["fee_bps"] + costs["slippage_bps"] + costs["spread_bps"],
        "initial_capital": backtest_config["initial_capital"],
        "periods_per_year": backtest_config["periods_per_year"],
        "risk_free_rate": backtest_config["risk_free_rate"],
    }
    if args.data_file:
        frame = data.load_csv(args.data_file)
        data_source = f"csv:{Path(args.data_file).name}"
    else:
        frame = data.load_pair(symbol, data_config["source"],
                               timeframe=data_config["timeframe"],
                               lookback_days=data_config["lookback_days"],
                               cache_dir=str(ENGINE_DIR / data_config["cache_dir"]))
        data_source = data_config["source"]
    report = baseline.build_report(
        frame["close"].astype(float), REGISTRY, context, symbol=symbol,
        timeframe=data_config["timeframe"], data_source=data_source,
    )
    output = (Path(args.output) if args.output else
              ENGINE_DIR / "results" / f"baseline_{symbol.replace('/', '')}.json")
    baseline.write_report(report, output)
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
