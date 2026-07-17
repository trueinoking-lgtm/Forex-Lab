"""Held-out future validation for paper/backtest strategies only."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from .backtest import run
from .paper_sim import simulate


def _utc_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _point_in_time_signals(train: pd.Series, future: pd.Series, signal_fn) -> pd.Series:
    """Compute each future signal with only information observable at that bar."""
    values = []
    for i in range(len(future)):
        observed = pd.concat((train, future.iloc[:i + 1]))
        signal = signal_fn(observed)
        if not isinstance(signal, pd.Series) or signal.empty:
            raise ValueError("signal_fn must return a non-empty pandas Series")
        values.append(float(signal.reindex(observed.index).iloc[-1]))
    return pd.Series(values, index=future.index, dtype=float).clip(-1, 1).fillna(0.0)


def _paper_signals(signal: pd.Series, price: pd.Series) -> list[dict]:
    """Turn position changes into conservative, symmetric paper trade intents."""
    intents = []
    previous = 0.0
    for timestamp, raw_side in signal.items():
        side = 1 if raw_side > 0 else (-1 if raw_side < 0 else 0)
        if side and side != previous:
            reference = float(price.loc[timestamp])
            distance = max(abs(reference) * 0.01, np.finfo(float).eps)
            intents.append({
                "timestamp": str(timestamp), "side": "buy" if side > 0 else "sell",
                "stop_loss": reference - side * distance,
                "take_profit": reference + side * distance, "tradeable": True,
            })
        previous = side
    return intents


def held_out_validate(price: pd.Series, signal_fn, ctx: dict, cutoff: pd.Timestamp,
                      train_lookback_days: int = 756) -> dict:
    """Evaluate signals after ``cutoff`` without exposing future bars in advance."""
    series = pd.Series(price, dtype=float).dropna().sort_index()
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("price must have a DatetimeIndex")
    if series.index.tz is None:
        series.index = series.index.tz_localize("UTC")
    else:
        series.index = series.index.tz_convert("UTC")
    cutoff = _utc_timestamp(cutoff)
    train_start = cutoff - pd.Timedelta(days=int(train_lookback_days))
    train = series[(series.index >= train_start) & (series.index < cutoff)]
    future = series[series.index >= cutoff]
    if len(train) < 60 or len(future) < 60:
        raise ValueError(f"not enough held-out future data for cutoff {cutoff.date()}")

    signals = _point_in_time_signals(train, future, signal_fn)
    result = run(future, signals, ctx.get("cost_bps", 2.0),
                 ctx.get("initial_capital", 10000.0),
                 ctx.get("periods_per_year", 252), ctx.get("risk_free_rate", 0.0))
    simulated = simulate(_paper_signals(signals, future), future,
                         cost_bps=ctx.get("cost_bps", 2.0),
                         initial_capital=ctx.get("initial_capital", 10000.0))
    accuracy = directional_accuracy(simulated["trades"])
    return {
        "equity": result["equity"], "returns": result["returns"],
        "trades": simulated["trades"], "metrics": result["metrics"],
        "directional_accuracy": accuracy, "prediction_hits": accuracy["n"],
        "future_window_days": int((future.index[-1] - future.index[0]).days),
        "n": len(future),
    }


def directional_accuracy(trades: list[dict]) -> dict:
    """Summarize whether completed paper trades called direction correctly."""
    trades = trades or []
    pnls = []
    reasons = {"take_profit": 0, "stop_loss": 0, "series_end": 0}
    correct = 0
    for trade in trades:
        try:
            pnl = float(trade.get("pnl", 0.0))
        except (TypeError, ValueError):
            pnl = 0.0
        pnl = pnl if math.isfinite(pnl) else 0.0
        reason = trade.get("reason")
        if reason in reasons:
            reasons[reason] += 1
        correct += int(pnl > 0 or reason == "take_profit")
        pnls.append(pnl)
    n = len(trades)
    return {"hit_rate": correct / n if n else 0.0,
            "take_profit_hits": reasons["take_profit"],
            "stop_loss_hits": reasons["stop_loss"],
            "series_end_hits": reasons["series_end"],
            "avg_pnl": float(np.mean(pnls)) if pnls else 0.0, "n": n}
