"""Causal fixed-UTC H1 session breakout positions for research only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ohlc(price):
    if isinstance(price, pd.DataFrame):
        names = {str(c).lower(): c for c in price.columns}
        if not {"high", "low", "close"} <= set(names):
            raise ValueError("OHLC frame requires high, low, close columns")
        close = price[names["close"]].astype(float)
        high = price[names["high"]].astype(float)
        low = price[names["low"]].astype(float)
    else:
        close = pd.Series(price, dtype=float)
        high = low = close
    if not isinstance(close.index, pd.DatetimeIndex):
        raise ValueError("session breakout requires a DatetimeIndex")
    if close.index.tz is None:
        raise ValueError("session breakout timestamps must be timezone-aware UTC")
    close.index = close.index.tz_convert("UTC")
    high.index = low.index = close.index
    return high.sort_index(), low.sort_index(), close.sort_index()


def _hours(window):
    if isinstance(window, str):
        start, end = window.split("-")
        return int(start.split(":")[0]), int(end.split(":")[0])
    return int(window[0]), int(window[1])


def session_breakout(price, *, pair, range_start_hour=0, range_end_hour=7,
                     breakout_window=(7, 16), breakout_buffer=0.0,
                     min_range_atr=None, max_range_atr=None, atr_lookback=14,
                     stop_mode="opp_side", stop_atr=None, target_r=None,
                     max_holding="session_close", session_end_hour=16,
                     long_allowed=True, short_allowed=True) -> pd.Series:
    """Return causal desired positions; the ledger executes each change at t+1."""
    del pair  # pair is required for an explicit shared cross-pair call contract.
    if not (0 <= range_start_hour < range_end_hour <= 24):
        raise ValueError("range hours must satisfy 0 <= start < end <= 24")
    bstart, bend = _hours(breakout_window)
    if not (range_end_hour <= bstart < bend <= 24 and bstart < session_end_hour <= 24):
        raise ValueError("breakout/session hours must follow the range in one UTC day")
    if breakout_buffer not in (0, .05, .1) or atr_lookback != 14:
        raise ValueError("parameters outside preregistered bounds")
    if stop_mode not in ("opp_side", "atr"):
        raise ValueError("stop_mode must be opp_side or atr")
    if stop_mode == "atr" and stop_atr not in (1.0, 1.5):
        raise ValueError("ATR stop requires stop_atr 1.0 or 1.5")
    if target_r not in (None, 1.0, 1.5, 2.0):
        raise ValueError("target_r outside preregistered bounds")
    if max_holding not in (4, 8, "session_close"):
        raise ValueError("max_holding outside preregistered bounds")

    high, low, close = _ohlc(price)
    prev_close = close.shift(1)
    tr = pd.concat((high-low, (high-prev_close).abs(), (low-prev_close).abs()), axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/atr_lookback, adjust=False, min_periods=atr_lookback).mean()
    out = pd.Series(0.0, index=close.index)
    held = 0; entry = stop = target = np.nan; age = 0
    used_long = used_short = False; current_day = None; rh = rl = np.nan

    for i, ts in enumerate(close.index):
        day, hour, px = ts.normalize(), ts.hour, float(close.iloc[i])
        if current_day is None or day != current_day:
            current_day = day; used_long = used_short = False
            rh = rl = np.nan
        mask = (close.index.normalize() == day) & (close.index.hour >= range_start_hour) & (close.index.hour < range_end_hour)
        completed = mask & (close.index <= ts)
        if completed.any():
            rh = float(high.loc[completed].max()); rl = float(low.loc[completed].min())

        if held:
            age += 1
            hit_stop = px <= stop if held > 0 else px >= stop
            hit_target = np.isfinite(target) and (px >= target if held > 0 else px <= target)
            time_exit = (max_holding != "session_close" and age >= max_holding) or hour >= session_end_hour
            if hit_stop or hit_target or time_exit:
                held = 0; entry = stop = target = np.nan; age = 0

        complete_range = hour >= range_end_hour and np.isfinite(rh) and np.isfinite(rl)
        distance = float(atr.iloc[i]) if np.isfinite(atr.iloc[i]) else np.nan
        range_ok = complete_range and np.isfinite(distance) and (
            min_range_atr is None or rh-rl >= min_range_atr*distance) and (
            max_range_atr is None or rh-rl <= max_range_atr*distance)
        in_window = bstart <= hour < bend
        direction = (1 if range_ok and in_window and long_allowed and not used_long and px > rh + breakout_buffer*distance
                     else -1 if range_ok and in_window and short_allowed and not used_short and px < rl - breakout_buffer*distance
                     else 0)
        if direction and direction != held:
            held = direction; entry = px; age = 0
            used_long |= direction > 0; used_short |= direction < 0
            risk = (entry-rl if direction > 0 else rh-entry) if stop_mode == "opp_side" else stop_atr*distance
            stop = (rl if direction > 0 else rh) if stop_mode == "opp_side" else entry-direction*risk
            target = entry + direction*target_r*risk if target_r is not None else np.nan
        out.iloc[i] = float(held)
    return out.reindex(price.index).fillna(0.0)
