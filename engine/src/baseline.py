"""Research-only baseline controls for strategy backtests.

These controls deliberately live outside ``strategies.REGISTRY``.  They produce
position series for the existing backtester and cannot submit or simulate an
order.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .canonical_eval import evaluate_strategy_canonical


DEFAULT_RANDOM_SEEDS = (7, 19, 41)


def no_trade(price: pd.Series) -> pd.Series:
    return pd.Series(0.0, index=price.index)


def buy_and_hold(price: pd.Series) -> pd.Series:
    return pd.Series(1.0, index=price.index)


def fixed_period_momentum(price: pd.Series, period: int = 20) -> pd.Series:
    change = price.pct_change(period)
    return np.sign(change).fillna(0.0).astype(float)


def sma_crossover(price: pd.Series, fast: int = 20, slow: int = 50) -> pd.Series:
    fast_ma = price.rolling(fast, min_periods=fast).mean()
    slow_ma = price.rolling(slow, min_periods=slow).mean()
    return np.sign(fast_ma - slow_ma).fillna(0.0).astype(float)


def circular_shift(signal: pd.Series, seed: int) -> pd.Series:
    """Randomize entry alignment while preserving each relative exit/run length."""
    if len(signal) < 2:
        return signal.copy().astype(float)
    rng = np.random.default_rng(seed)
    offset = int(rng.integers(1, len(signal)))
    shifted = np.roll(signal.to_numpy(dtype=float), offset)
    return pd.Series(shifted, index=signal.index)


def _finite(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def _metrics(result: dict) -> dict:
    return {key: _finite(value) for key, value in result.get("metrics", {}).items()}


def _evaluate(price: pd.Series, signal_fn, ctx: dict, name="control", symbol="unknown") -> dict:
    result = evaluate_strategy_canonical(price, lambda p: signal_fn(p), ctx,
                                         strategy=name, symbol=symbol,
                                         spread_bps=ctx.get("spread_bps", ctx["cost_bps"]),
                                         slippage_bps=ctx.get("slippage_bps", 0),
                                         commission_bps=ctx.get("commission_bps", 0))
    return {"metrics": _metrics({"metrics": result["portfolio_metrics"]}),
            "window_returns": [_finite(value) for value in result["window_returns"]],
            "canonical": {k: result[k] for k in ("lifecycle_metrics", "score", "robustness",
                                                   "oos_return", "profit_factor", "gates",
                                                   "rejection_reasons", "eligible")}}


def build_report(price: pd.Series, strategies: dict, ctx: dict, *, symbol: str,
                 timeframe: str, data_source: str,
                 random_seeds: tuple[int, ...] = DEFAULT_RANDOM_SEEDS) -> dict:
    """Compare registered strategies with deterministic research controls."""
    controls = {
        "no_trade": {"parameters": {}, "result": _evaluate(price, no_trade, ctx, "no_trade", symbol)},
        "buy_and_hold": {"parameters": {}, "result": _evaluate(price, buy_and_hold, ctx, "buy_and_hold", symbol)},
        "fixed_period_momentum": {
            "parameters": {"period": 20},
            "result": _evaluate(price, lambda p: fixed_period_momentum(p, 20), ctx, "fixed_period_momentum", symbol),
        },
        "sma_crossover": {
            "parameters": {"fast": 20, "slow": 50},
            "result": _evaluate(price, lambda p: sma_crossover(p, 20, 50), ctx, "sma_crossover", symbol),
        },
    }
    strategy_results = {}
    for name in sorted(strategies):
        fn, params = strategies[name]
        actual = _evaluate(price, lambda p, f=fn, kw=params: f(p, **kw), ctx, name, symbol)
        randomized = []
        for seed in random_seeds:
            randomized.append({
                "seed": seed,
                "result": _evaluate(
                    price,
                    lambda p, f=fn, kw=params, s=seed: circular_shift(f(p, **kw), s),
                    ctx,
                ),
            })
        strategy_results[name] = {
            "parameters": params,
            "result": actual,
            "randomized_entry_controls": randomized,
        }

    fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(price, index=True).values.tobytes()
    ).hexdigest()
    return {
        "schema_version": 1,
        "purpose": "research_baseline_controls_only",
        "symbol": symbol,
        "timeframe": timeframe,
        "data_source": data_source,
        "data_fingerprint_sha256": fingerprint,
        "date_range": {"start": price.index[0].isoformat(), "end": price.index[-1].isoformat()},
        "bar_count": len(price),
        "cost_bps": ctx["cost_bps"],
        "walk_forward": dict(ctx["walk_forward"]),
        "randomized_control": {
            "method": "seeded circular shift of each strategy position series",
            "preserves": "position values, holding-period distribution and relative exit timing",
            "costs": "same backtest cost model; charged on every randomized position change",
            "seeds": list(random_seeds),
        },
        "controls": controls,
        "strategies": strategy_results,
    }


def write_report(report: dict, path: str | Path) -> Path:
    """Atomically write canonical JSON so deterministic reruns are byte-identical."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return destination
