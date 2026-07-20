"""Causal, close-only trend continuation research signal.

The registry contract supplies a close series.  ATR and ADX therefore use
close-to-close true range and directional movement.  Every value at index t is
computed exclusively from observations at or before t; the shared backtester
applies the resulting position on t+1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


VOL_PERCENTILE_WINDOW = 252


def _validate(fast: int, slow: int, adx_threshold: float, atr_lookback: int,
              vol_lookback: int, vol_low_pct: float, vol_high_pct: float,
              stop_atr: float | None) -> None:
    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError("fast and slow must be positive with fast < slow")
    if atr_lookback <= 1 or vol_lookback <= 1:
        raise ValueError("lookbacks must be greater than one")
    if adx_threshold < 0:
        raise ValueError("adx_threshold must be non-negative")
    if not 0 <= vol_low_pct <= vol_high_pct <= 100:
        raise ValueError("volatility percentiles must satisfy 0 <= low <= high <= 100")
    if stop_atr is not None and stop_atr <= 0:
        raise ValueError("stop_atr must be positive or None")


def _wilder_atr_adx(price: pd.Series, period: int) -> tuple[pd.Series, pd.Series]:
    change = price.diff()
    true_range = change.abs()
    plus_dm = change.clip(lower=0.0)
    minus_dm = (-change).clip(lower=0.0)
    kwargs = {"alpha": 1.0 / period, "adjust": False, "min_periods": period}
    atr = true_range.ewm(**kwargs).mean()
    plus_di = 100.0 * plus_dm.ewm(**kwargs).mean().div(atr.replace(0.0, np.nan))
    minus_di = 100.0 * minus_dm.ewm(**kwargs).mean().div(atr.replace(0.0, np.nan))
    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs().div(di_sum.replace(0.0, np.nan))
    dx = dx.mask((di_sum == 0.0) & atr.notna(), 0.0)
    adx = dx.ewm(**kwargs).mean()
    return atr, adx


def _rolling_percentile(values: pd.Series, window: int = VOL_PERCENTILE_WINDOW) -> pd.Series:
    """Causal percentile rank of the latest observation in a trailing window."""
    minimum = min(window, max(20, window // 5))

    def latest_rank(sample: np.ndarray) -> float:
        current = sample[-1]
        if not np.isfinite(current):
            return np.nan
        valid = sample[np.isfinite(sample)]
        if len(valid) < minimum or np.nanmax(valid) == np.nanmin(valid):
            return np.nan
        return 100.0 * float(np.count_nonzero(valid <= current)) / len(valid)

    return values.rolling(window, min_periods=minimum).apply(latest_rank, raw=True)


def trend_continuation(price: pd.Series, *, fast: int = 12, slow: int = 60,
                       adx_threshold: float = 22, atr_lookback: int = 14,
                       vol_lookback: int = 20, vol_low_pct: float = 20,
                       vol_high_pct: float = 90, stop_atr: float | None = 2.0,
                       trailing: bool = True) -> pd.Series:
    """Return positions in {-1, 0, 1}; execution lag is owned by backtest.run."""
    _validate(fast, slow, adx_threshold, atr_lookback, vol_lookback,
              vol_low_pct, vol_high_pct, stop_atr)
    close = pd.Series(price, dtype=float).sort_index()
    fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    atr, adx = _wilder_atr_adx(close, atr_lookback)
    realized_vol = close.pct_change().rolling(vol_lookback, min_periods=vol_lookback).std()
    vol_percentile = _rolling_percentile(realized_vol)
    allowed = (adx >= adx_threshold) & vol_percentile.between(vol_low_pct, vol_high_pct)
    direction = pd.Series(np.sign(fast_ema - slow_ema), index=close.index).fillna(0.0)
    desired = direction.where(allowed, 0.0)

    if stop_atr is None:
        return desired.astype(float).reindex(price.index).fillna(0.0)

    output = pd.Series(0.0, index=close.index)
    held = 0.0
    anchor = np.nan
    for i in range(len(close)):
        want = float(desired.iloc[i])
        px = float(close.iloc[i])
        distance = float(stop_atr * atr.iloc[i]) if np.isfinite(atr.iloc[i]) else np.nan
        if want == 0.0 or (held and want != held):
            held, anchor = 0.0, np.nan
        if held == 0.0 and want != 0.0 and np.isfinite(distance):
            held, anchor = want, px
        elif held != 0.0:
            if trailing:
                anchor = max(anchor, px) if held > 0 else min(anchor, px)
            stopped = (held > 0 and px <= anchor - distance) or (held < 0 and px >= anchor + distance)
            if stopped:
                held, anchor = 0.0, np.nan
        output.iloc[i] = held
    return output.reindex(price.index).fillna(0.0).astype(float)
