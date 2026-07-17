"""Paper-only trade simulator and honest performance reporting.

This module consumes approved signals; it never talks to a broker or places orders.
Signals are filled at the next available close, then evaluated against subsequent
closes for their stop or target.  With close-only data, intrabar ordering cannot be
known, so no intrabar fills are invented.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from .signals import risk_check

try:  # Batch 1 is optional in older clones.
    from .execution.risk_budget import PortfolioRiskState  # type: ignore
except ImportError:  # pragma: no cover - exercised only when Batch 1 is installed
    PortfolioRiskState = None


def _finite(value, default=0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def metrics_from_returns(returns: list[float], equity_curve: list[float],
                         periods_per_year: int = 252) -> dict:
    """Compute metrics without hiding empty, losing, or low-variance samples."""
    values = np.asarray([_finite(r) for r in returns], dtype=float)
    equity = np.asarray([_finite(v) for v in equity_curve], dtype=float)
    mean = float(values.mean()) if values.size else 0.0
    std = float(values.std(ddof=1)) if values.size > 1 else 0.0
    sharpe = mean / std * math.sqrt(periods_per_year) if std > 0 else 0.0
    downside = values[values < 0]
    downside_dev = float(np.sqrt(np.mean(np.square(downside)))) if downside.size else 0.0
    sortino = mean / downside_dev * math.sqrt(periods_per_year) if downside_dev > 0 else 0.0
    wins = float(values[values > 0].sum()) if values.size else 0.0
    losses = float(-values[values < 0].sum()) if values.size else 0.0
    profit_factor = wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)
    win_rate = float(np.mean(values > 0)) if values.size else 0.0

    if equity.size:
        peaks = np.maximum.accumulate(equity)
        drawdowns = np.divide(peaks - equity, peaks, out=np.zeros_like(equity), where=peaks != 0)
        max_drawdown = float(drawdowns.max())
        total_return = float(equity[-1] / equity[0] - 1.0) if equity[0] else 0.0
    else:
        max_drawdown = total_return = 0.0
    return {
        "total_return": total_return, "sharpe": sharpe, "sortino": sortino,
        "profit_factor": profit_factor, "win_rate": win_rate,
        "max_drawdown": max_drawdown, "trade_count": int(values.size),
        "expectancy": mean, "return_std": std,
    }


def overfitting_flags(metrics: dict, in_sample_return: float | None = None,
                      oos_return: float | None = None) -> list[str]:
    """Return plain-language warnings for implausibly clean headline metrics."""
    flags = []
    if _finite(metrics.get("sharpe")) > 3:
        flags.append("Sharpe ratio above 3 may indicate overfitting.")
    if _finite(metrics.get("profit_factor"), float("inf")) > 4:
        flags.append("Profit factor above 4 may indicate overfitting or too few losses.")
    if _finite(metrics.get("win_rate")) > 0.8:
        flags.append("Win rate above 80% may indicate overfitting.")
    if abs(_finite(metrics.get("max_drawdown"))) < 0.05:
        flags.append("Maximum drawdown below 5% may be unrealistically low.")
    if "return_std" in metrics and _finite(metrics.get("return_std")) < 1e-10:
        flags.append("Return series is nearly perfectly smooth; check for leakage or sparse data.")
    if in_sample_return is not None and oos_return is not None:
        ins, oos = _finite(in_sample_return), _finite(oos_return)
        if ins > 0 and oos < 0.3 * ins:
            flags.append("Out-of-sample return is below 30% of in-sample return.")
    return flags


def _side(signal: dict) -> int:
    raw = signal.get("side", signal.get("direction"))
    if isinstance(raw, str):
        return 1 if raw.lower() == "buy" else (-1 if raw.lower() == "sell" else 0)
    return 1 if _finite(raw) > 0 else (-1 if _finite(raw) < 0 else 0)


def simulate(signals: list[dict], price: pd.Series, cost_bps: float,
             initial_capital: float = 10000.0, risk_pct: float = 0.75) -> dict:
    """Fill tradeable signals on the next bar and close at SL, TP, or series end."""
    series = pd.Series(price, dtype=float).dropna().sort_index()
    if series.empty:
        raise ValueError("price series must contain at least one finite value")

    indexed: list[tuple[pd.Timestamp, dict]] = []
    for signal in signals:
        if signal.get("tradeable", True) is not True:
            continue
        try:
            timestamp = pd.Timestamp(signal["timestamp"])
            if isinstance(series.index, pd.DatetimeIndex):
                timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        except (KeyError, TypeError, ValueError):
            continue
        indexed.append((timestamp, signal))
    indexed.sort(key=lambda item: item[0])

    capital = float(initial_capital)
    curve = [capital]
    trades, trade_returns = [], []
    available_after = -1
    risk_state = None
    if PortfolioRiskState is not None:  # constructor varies by Batch 1 config; fail optional.
        try:  # pragma: no cover
            risk_state = PortfolioRiskState()
        except TypeError:
            risk_state = None

    for timestamp, signal in indexed:
        if risk_state is not None and risk_state.halt_new_entries():  # pragma: no cover
            continue
        fill_pos = int(series.index.searchsorted(timestamp, side="left"))
        # This close-only simulator holds one position at a time. Skipping an
        # overlapping entry prevents a later signal from being sized with P&L
        # that, at its timestamp, had not yet been realized.
        if fill_pos >= len(series) or fill_pos <= available_after:
            continue
        direction = _side(signal)
        entry = float(series.iloc[fill_pos])
        stop = _finite(signal.get("stop_loss"), entry)
        target = _finite(signal.get("take_profit"), entry)
        valid_geometry = ((direction > 0 and stop < entry < target) or
                          (direction < 0 and target < entry < stop))
        if not valid_geometry:
            continue
        sized = risk_check(capital, risk_pct, entry, stop)
        if not sized.get("pass"):
            continue
        units = float(sized["units"])
        exit_pos, exit_price, reason = len(series) - 1, float(series.iloc[-1]), "series_end"
        for pos in range(fill_pos + 1, len(series)):
            current = float(series.iloc[pos])
            if (direction > 0 and current <= stop) or (direction < 0 and current >= stop):
                exit_pos, exit_price, reason = pos, current, "stop_loss"
                break
            if (direction > 0 and current >= target) or (direction < 0 and current <= target):
                exit_pos, exit_price, reason = pos, current, "take_profit"
                break
        gross = direction * (exit_price - entry) * units
        cost = (entry + exit_price) * units * max(0.0, float(cost_bps)) / 10000.0
        pnl = gross - cost
        before = capital
        capital += pnl
        trade_return = pnl / before if before else 0.0
        trade_returns.append(trade_return)
        curve.append(capital)
        available_after = exit_pos
        trades.append({
            "entry": entry, "exit": exit_price,
            "side": "buy" if direction > 0 else "sell", "units": units,
            "pnl": pnl, "reason": reason, "entry_time": str(series.index[fill_pos]),
            "exit_time": str(series.index[exit_pos]), "hold_bars": exit_pos - fill_pos,
        })
        if risk_state is not None:  # pragma: no cover
            risk_state.register_close(pnl)
            risk_state.update_equity(capital)

    metrics = metrics_from_returns(trade_returns, curve)
    metrics["avg_hold_bars"] = (float(np.mean([t["hold_bars"] for t in trades]))
                                if trades else 0.0)
    return {"equity_curve": curve, "trades": trades, "metrics": metrics,
            "overfitting_flags": overfitting_flags(metrics)}
