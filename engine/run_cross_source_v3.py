#!/usr/bin/env python3
"""Regenerate the paper-only MT5/yfinance cross-source research artifacts."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from src.baseline import (buy_and_hold, circular_shift, fixed_period_momentum,
                              no_trade, sma_crossover)
    from src.canonical_eval import evaluate_strategy_canonical
    from src.signals import classify_regime
    from strategies.registry import REGISTRY
except ImportError:  # Support repository-root imports used by the test suite.
    from engine.src.baseline import (buy_and_hold, circular_shift, fixed_period_momentum,
                                     no_trade, sma_crossover)
    from engine.src.canonical_eval import evaluate_strategy_canonical
    from engine.src.signals import classify_regime
    from engine.strategies.registry import REGISTRY

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
SOURCES = {
    "mt5": DATA / "raw_mt5_EURUSD_1d_retry.csv",
    "yfinance": DATA / "raw_yfinance_EURUSD=X_1d.csv",
}
OHLC = ["open", "high", "low", "close"]
PERIODS = {
    "2010-2014": ("2010-01-01", "2015-01-01"),
    "2015-2019": ("2015-01-01", "2020-01-01"),
    "2020-2022": ("2020-01-01", "2023-01-01"),
    "2023-present": ("2023-01-01", None),
}


def clean(value):
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items() if key != "trades"}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def write_json(name: str, value) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / name).write_text(
        json.dumps(clean(value), indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def load_source(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    for column in OHLC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def fingerprint(frame: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()


def integrity(frame: pd.DataFrame, path: Path) -> dict:
    values = frame[OHLC]
    finite = pd.Series(np.isfinite(values).all(axis=1), index=frame.index)
    valid = (finite & (values > 0).all(axis=1)
             & (frame.high >= frame[["open", "close"]].max(axis=1))
             & (frame.low <= frame[["open", "close"]].min(axis=1))
             & (frame.high >= frame.low))
    try:
        display_path = str(path.relative_to(ROOT))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "frame_fingerprint": fingerprint(frame),
        "row_count": len(frame),
        "first": frame.index.min(),
        "last": frame.index.max(),
        "sorted": bool(frame.index.is_monotonic_increasing),
        "unique": bool(frame.index.is_unique),
        "invalid_ohlc_count": int((~valid).sum()),
        "duplicate_count": int(frame.index.duplicated().sum()),
        "weekend_count": int((frame.index.dayofweek >= 5).sum()),
    }


def definitions():
    ema_fn, ema_params = REGISTRY["ema_crossover"]
    randomized = lambda price: circular_shift(ema_fn(price, **ema_params), 7)
    controls = {
        "no_trade": (no_trade, {}),
        "buy_and_hold": (buy_and_hold, {}),
        "simple_ma_crossover": (sma_crossover, {"fast": 20, "slow": 50}),
        "fixed_period_momentum": (fixed_period_momentum, {"period": 20}),
        "fixed_seed_randomized_entry": (randomized, {}),
    }
    return {**REGISTRY, **controls}


def context(cost_bps: int = 3) -> dict:
    return {"walk_forward": {"train_days": 252, "test_days": 30, "step_days": 30},
            "cost_bps": cost_bps, "initial_capital": 10000, "periods_per_year": 252,
            "risk_free_rate": 0, "min_trades": 8}


def evaluate(price: pd.Series, name: str, fn, params: dict, cost_bps: int = 3) -> dict:
    result = evaluate_strategy_canonical(
        price, fn, context(cost_bps), strategy=name, symbol="EURUSD", params=params,
        spread_bps=cost_bps, slippage_bps=0, commission_bps=0,
    )
    life = result["lifecycle_metrics"]
    portfolio = result["portfolio_metrics"]
    return {
        "completed_lifecycle_trades": life["trade_count"],
        "open_lifecycle_trades": life["open_trade_count"],
        "profit_factor": life["profit_factor"],
        "expectancy": life["expectancy"],
        "return": result["oos_return"],
        "max_drawdown": portfolio.get("max_drawdown"),
        "robustness": result["robustness"],
        "score": result["score"],
        "gates": result["gates"],
        "eligible": result["eligible"],
        "trades": result["trades"],
    }


def summarize_evaluation(result: dict) -> dict:
    return clean(result)


def source_comparison(mt5: pd.DataFrame, yf: pd.DataFrame) -> dict:
    common = mt5.index.intersection(yf.index)
    left, right = mt5.loc[common], yf.loc[common]
    differences = (left[OHLC] - right[OHLC]).abs()
    stats = {
        column: {"median": differences[column].median(),
                 "p95": differences[column].quantile(0.95),
                 "max": differences[column].max()}
        for column in OHLC
    }
    mt5_returns, yf_returns = left.close.pct_change(), right.close.pct_change()
    comparable = mt5_returns.notna() & yf_returns.notna()
    sign_agreement = (np.sign(mt5_returns[comparable]) == np.sign(yf_returns[comparable]))
    ema_fn, ema_params = REGISTRY["ema_crossover"]
    mt5_pos, yf_pos = ema_fn(left.close, **ema_params), ema_fn(right.close, **ema_params)
    mt5_eval = evaluate(left.close, "ema_crossover", ema_fn, ema_params)
    yf_eval = evaluate(right.close, "ema_crossover", ema_fn, ema_params)
    mt5_trades = {(t["entry_ts"], t["exit_ts"]) for t in mt5_eval["trades"] if not t["still_open_at_end"]}
    yf_trades = {(t["entry_ts"], t["exit_ts"]) for t in yf_eval["trades"] if not t["still_open_at_end"]}
    return {
        "scope": {"start": common.min(), "end": common.max()},
        "sources": {name: integrity(frame, SOURCES[name]) for name, frame in (("mt5", mt5), ("yfinance", yf))},
        "timestamp_overlap": len(common),
        "source_only_candles": {
            "mt5_count": len(mt5.index.difference(yf.index)),
            "mt5_dates": list(mt5.index.difference(yf.index)),
            "yfinance_count": len(yf.index.difference(mt5.index)),
            "yfinance_dates": list(yf.index.difference(mt5.index)),
        },
        "absolute_ohlc_difference": stats,
        "return_direction_agreement": {"comparable_days": int(comparable.sum()),
                                       "agreeing_days": int(sign_agreement.sum()),
                                       "rate": float(sign_agreement.mean())},
        "annualized_return_volatility": {
            "mt5": float(mt5_returns.std() * math.sqrt(252)),
            "yfinance": float(yf_returns.std() * math.sqrt(252)),
            "absolute_difference": float(abs(mt5_returns.std() - yf_returns.std()) * math.sqrt(252)),
        },
        "ema_crossover_position_agreement": {
            "correlation": float(mt5_pos.corr(yf_pos)),
            "exact_rate": float((mt5_pos == yf_pos).mean()),
        },
        "ema_crossover_lifecycle_trade_agreement": {
            "mt5_closed": len(mt5_trades), "yfinance_closed": len(yf_trades),
            "matching_entry_exit_dates": len(mt5_trades & yf_trades),
            "union_entry_exit_dates": len(mt5_trades | yf_trades),
        },
        "policy": "Evaluate each source separately; never merge candles across sources.",
    }


def period_and_regime(frames: dict[str, pd.DataFrame], defs: dict) -> dict:
    output = {"periods": {}, "regimes": {}, "regime_definition": {
        "trend": "ADX > 25", "range": "ADX < 20",
        "volatility": "20-day close-return standard deviation split at each source median"}}
    for source, frame in frames.items():
        price = frame.close
        output["periods"][source] = {}
        for label, (start, end) in PERIODS.items():
            subset = price[(price.index >= start) & ((price.index < end) if end else True)]
            output["periods"][source][label] = {
                "bars": len(subset),
                "evaluations": {name: summarize_evaluation(evaluate(subset, name, fn, params))
                                for name, (fn, params) in defs.items()} if len(subset) >= 300 else {},
            }
        regimes = []
        for index in range(len(frame)):
            if index < 28:
                regimes.append("unknown")
            else:
                regimes.append(classify_regime(frame.close.iloc[:index + 1], frame.high.iloc[:index + 1],
                                               frame.low.iloc[:index + 1])[0])
        volatility = price.pct_change().rolling(20).std()
        masks = {"high_vol": volatility >= volatility.median(), "low_vol": volatility < volatility.median(),
                 "trending": pd.Series(regimes, index=frame.index) == "trend",
                 "ranging": pd.Series(regimes, index=frame.index) == "range"}
        output["regimes"][source] = {
            regime: {"bars": int(mask.sum()), "strategy_selected_bar_returns": {
                name: float((fn(price, **params).shift(1) * price.pct_change())[mask].sum())
                for name, (fn, params) in defs.items()}}
            for regime, mask in masks.items()
        }
    return output


def main() -> int:
    frames = {name: load_source(path) for name, path in SOURCES.items()}
    defs = definitions()
    write_json("source_comparison.json", source_comparison(frames["mt5"], frames["yfinance"]))
    canonical = {}
    for source, frame in frames.items():
        canonical[source] = {
            "source": source, "integrity": integrity(frame, SOURCES[source]),
            "costs_bps": 3, "evaluations": {
                name: summarize_evaluation(evaluate(frame.close, name, fn, params))
                for name, (fn, params) in defs.items()},
        }
        write_json(f"{source}_canonical.json", canonical[source])
    write_json("mt5_integrity.json", canonical["mt5"]["integrity"])
    write_json("period_regime.json", period_and_regime(frames, defs))
    sensitivity = {source: {name: {
        f"total_friction_{cost}bps": summarize_evaluation(evaluate(frame.close, name, fn, params, cost))
        for cost in (3, 5, 8, 12)} for name, (fn, params) in defs.items()}
        for source, frame in frames.items()}
    write_json("cost_sensitivity.json", sensitivity)
    recent = frames["mt5"].loc["2023-07-20":"2026-07-17"]
    recent_yf = frames["yfinance"].loc["2023-07-20":"2026-07-17"]
    ema_fn, ema_params = REGISTRY["ema_crossover"]
    observed = evaluate(recent.close, "ema_crossover", ema_fn, ema_params)
    observed_yf = evaluate(recent_yf.close, "ema_crossover", ema_fn, ema_params)
    write_json("mt5_v2_reconciliation.json", {
        "slice": {"start": "2023-07-20", "end": "2026-07-17", "rows": len(recent)},
        "v2_yfinance_expected": {"rows": 777, "closed": 20, "open": 1,
                                 "profit_factor": 1.186232434520887, "eligible": False},
        "mt5_observed": summarize_evaluation(observed),
        "mt5_reproduces_v2": False,
        "mt5_difference_note": "Lifecycle counts and eligibility match, but broker/session candles do not reproduce the yfinance PF.",
        "yfinance_observed": {"rows": len(recent_yf), **summarize_evaluation(observed_yf)},
        "yfinance_reproduces_v2": bool(
            len(recent_yf) == 777
            and observed_yf["completed_lifecycle_trades"] == 20
            and observed_yf["open_lifecycle_trades"] == 1
            and abs(observed_yf["profit_factor"] - 1.186232434520887) < 1e-12
            and observed_yf["eligible"] is False
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
