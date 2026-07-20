"""Causal, close-only range mean-reversion research signals.

ADX(14) is Wilder-smoothed from close-to-close directional movement because
the strategy registry contract supplies only closes.  A bar is ranging iff
ADX is strictly below ``adx_threshold``.  Signals use data through bar t only;
the canonical backtester and lifecycle ledger execute them on t+1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .trend_continuation import _wilder_atr_adx


def _validate(lookback, adx_threshold, max_holding, atr_stop, target):
    if lookback <= 1 or adx_threshold < 0 or max_holding <= 0:
        raise ValueError("lookback > 1, ADX >= 0, and max_holding > 0 required")
    if atr_stop is not None and atr_stop <= 0:
        raise ValueError("atr_stop must be positive or None")
    if target is not None and target <= 0:
        raise ValueError("profit_target_atr must be positive or None")


def _positions(close, entry, mean_exit, ranging, atr, max_holding,
               atr_stop, target, trailing=False):
    out = pd.Series(0.0, index=close.index)
    held, entry_px, anchor, age = 0.0, np.nan, np.nan, 0
    for i in range(len(close)):
        px, distance = float(close.iloc[i]), float(atr.iloc[i])
        allowed = bool(ranging.iloc[i])
        if held:
            age += 1
            if trailing:
                anchor = max(anchor, px) if held > 0 else min(anchor, px)
            stop_anchor = anchor if trailing else entry_px
            stopped = atr_stop is not None and np.isfinite(distance) and (
                (held > 0 and px <= stop_anchor - atr_stop * distance) or
                (held < 0 and px >= stop_anchor + atr_stop * distance))
            won = target is not None and np.isfinite(distance) and (
                (held > 0 and px >= entry_px + target * distance) or
                (held < 0 and px <= entry_px - target * distance))
            if not allowed or bool(mean_exit.iloc[i]) or age >= max_holding or stopped or won:
                held, entry_px, anchor, age = 0.0, np.nan, np.nan, 0
        if not held and allowed and entry.iloc[i] != 0 and np.isfinite(distance):
            held = float(entry.iloc[i])
            entry_px = anchor = px
            age = 0
        out.iloc[i] = held
    return out.astype(float)


def rsi_range_reversion(price: pd.Series, *, rsi_period: int = 14,
                        rsi_lower: float = 25, rsi_upper: float = 75,
                        adx_threshold: float = 20, max_holding: int = 10,
                        atr_stop: float | None = 1.5,
                        profit_target_atr: float | None = 1.0,
                        trailing: bool = False) -> pd.Series:
    _validate(rsi_period, adx_threshold, max_holding, atr_stop, profit_target_atr)
    if not 0 <= rsi_lower < 50 < rsi_upper <= 100:
        raise ValueError("RSI bounds must straddle 50")
    close = pd.Series(price, dtype=float).sort_index()
    atr, adx = _wilder_atr_adx(close, 14)
    delta = close.diff(); gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    rs = gain.ewm(alpha=1/rsi_period, adjust=False, min_periods=rsi_period).mean().div(
        loss.ewm(alpha=1/rsi_period, adjust=False, min_periods=rsi_period).mean().replace(0, np.nan))
    rsi = 100 - 100 / (1 + rs)
    entry = pd.Series(np.select([rsi <= rsi_lower, rsi >= rsi_upper], [1, -1], 0), index=close.index)
    out = _positions(close, entry, (rsi-50).abs() <= 2.5, adx < adx_threshold,
                     atr, max_holding, atr_stop, profit_target_atr, trailing)
    return out.reindex(price.index).fillna(0.0)


def zscore_range_reversion(price: pd.Series, *, z_lookback: int = 20,
                           z_entry: float = 2.0, adx_threshold: float = 20,
                           max_holding: int = 10, atr_stop: float | None = 1.5,
                           profit_target_atr: float | None = 1.0) -> pd.Series:
    _validate(z_lookback, adx_threshold, max_holding, atr_stop, profit_target_atr)
    if z_entry <= 0: raise ValueError("z_entry must be positive")
    close = pd.Series(price, dtype=float).sort_index(); atr, adx = _wilder_atr_adx(close, 14)
    z = (close-close.rolling(z_lookback).mean())/close.rolling(z_lookback).std().replace(0, np.nan)
    entry = pd.Series(np.select([z <= -z_entry, z >= z_entry], [1, -1], 0), index=close.index)
    out = _positions(close, entry, z.abs() <= .1, adx < adx_threshold, atr,
                     max_holding, atr_stop, profit_target_atr)
    return out.reindex(price.index).fillna(0.0)


def bollinger_range_reversion(price: pd.Series, *, bb_lookback: int = 20,
                              bb_width: float = 2.0, adx_threshold: float = 20,
                              max_holding: int = 10, atr_stop: float | None = 1.5,
                              profit_target_atr: float | None = 1.0) -> pd.Series:
    _validate(bb_lookback, adx_threshold, max_holding, atr_stop, profit_target_atr)
    if bb_width <= 0: raise ValueError("bb_width must be positive")
    close = pd.Series(price, dtype=float).sort_index(); atr, adx = _wilder_atr_adx(close, 14)
    mid = close.rolling(bb_lookback).mean(); std = close.rolling(bb_lookback).std()
    entry = pd.Series(np.select([close <= mid-bb_width*std, close >= mid+bb_width*std], [1, -1], 0), index=close.index)
    out = _positions(close, entry, (close-mid).abs() <= .05*std, adx < adx_threshold,
                     atr, max_holding, atr_stop, profit_target_atr)
    return out.reindex(price.index).fillna(0.0)
