"""Strategy registry: 5 named forex strategies (v1).

Each strategy is a function(price, **params) -> pd.Series(position in [-1,1])
computed with history <= t only (no look-ahead). All satisfy the backtester's
"signal over train+test, evaluate test" contract.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema(price: pd.Series, span: int) -> pd.Series:
    return price.ewm(span=span, adjust=False).mean()


def ema_crossover(price: pd.Series, fast: int = 12, slow: int = 26, **kw) -> pd.Series:
    f, s = ema(price, fast), ema(price, slow)
    pos = pd.Series(0.0, index=price.index)
    pos[f > s] = 1.0
    pos[f < s] = -1.0
    return pos.fillna(0.0)


def ema_trend_pullback(price: pd.Series, fast: int = 12, slow: int = 26,
                       pullback_z: float = 1.0, **kw) -> pd.Series:
    f, s = ema(price, fast), ema(price, slow)
    trend_up = f > s
    trend_down = f < s
    logp = np.log(price)
    z = (logp - logp.rolling(20).mean()) / logp.rolling(20).std()
    pos = pd.Series(0.0, index=price.index)
    # long when uptrend AND price pulled back (z < -pullback_z)
    pos[trend_up & (z < -pullback_z)] = 1.0
    pos[trend_down & (z > pullback_z)] = -1.0
    return pos.fillna(0.0)


def rsi(price: pd.Series, period: int = 14) -> pd.Series:
    delta = price.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace([np.inf, -np.inf], np.nan)
    return 100 - 100 / (1 + rs)


def rsi_mean_reversion(price: pd.Series, period: int = 14, oversold: float = 30.0,
                       overbought: float = 70.0, **kw) -> pd.Series:
    r = rsi(price, period).fillna(50)
    pos = pd.Series(0.0, index=price.index)
    pos[r < oversold] = 1.0
    pos[r > overbought] = -1.0
    return pos


def macd(price: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_f = price.ewm(span=fast, adjust=False).mean()
    ema_s = price.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def macd_trend_confirmation(price: pd.Series, fast: int = 12, slow: int = 26,
                            signal: int = 9, **kw) -> pd.Series:
    m, s = macd(price, fast, slow, signal)
    hist = m - s
    pos = pd.Series(0.0, index=price.index)
    pos[hist > 0] = 1.0      # momentum up
    pos[hist < 0] = -1.0
    return pos.fillna(0.0)


def london_breakout(price: pd.Series, lookback: int = 20, k: float = 0.5, **kw) -> pd.Series:
    """Daily-adapted London breakout: go long when today's close breaks above
    the prior `lookback` high by k*ATR, short below prior low. (True session
    timing is a v3 intraday extension; v1 uses daily range.)"""
    high = price.rolling(lookback).max().shift(1)
    low = price.rolling(lookback).min().shift(1)
    rng = (price.rolling(lookback).max() - price.rolling(lookback).min()).shift(1)
    thr = k * rng
    pos = pd.Series(0.0, index=price.index)
    pos[price > high + thr] = 1.0
    pos[price < low - thr] = -1.0
    return pos.fillna(0.0)


# Registry: name -> (callable, default params)
REGISTRY = {
    "ema_crossover": (ema_crossover, {"fast": 12, "slow": 26}),
    "ema_trend_pullback": (ema_trend_pullback, {"fast": 12, "slow": 26, "pullback_z": 1.0}),
    "rsi_mean_reversion": (rsi_mean_reversion, {"period": 14, "oversold": 30, "overbought": 70}),
    "macd_trend_confirmation": (macd_trend_confirmation, {"fast": 12, "slow": 26, "signal": 9}),
    "london_breakout": (london_breakout, {"lookback": 20, "k": 0.5}),
}


def list_strategies() -> list[str]:
    return list(REGISTRY.keys())


def build_signal(name: str, price: pd.Series, **overrides) -> pd.Series:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy: {name}")
    fn, params = REGISTRY[name]
    params = {**params, **overrides}
    return fn(price, **params)
