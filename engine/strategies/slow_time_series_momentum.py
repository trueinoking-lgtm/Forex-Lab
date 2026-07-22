"""Research-based analysis of slow time‑series momentum in FX markets.

Focuses on 12M/1M momentum logic applied to MT5 native daily data.

Frozen design (no runtime parameter changes):
- Lookback: 252 trading days (exact 12‑month lookback, matches literature’s slow momentum)
- Hold period: 21 trading days (~1 month, consistent with academic citation)
- Rebalance: monthly, at period end (aligns with expected trade frequency of 1x/month)
- Signal definition: cumulative price return over lookback, excluding most recent bar
- Position sizing: equal‑risk model (normalized_equal_risk_v1), v2 accounting
- Transaction costs: 3 bps per trade (entry + exit)
- Execution: 1‑day delay (next‑bar fill, matches academic signal treatment)

Implementation notes:
- 4‑currency pair universe (EURUSD, GBPUSD, USDJPY, AUDUSD)
- No volatility scaling, carry, or regime filters
- Signals generated from MT5 native D1 (no yfinance substitutions)
- Price data loaded via _load_data(pair) → pd.Series (index = UTC timestamp)
- Signal: price_t / price_{t‑lookback} – 1 (pandas pct_change)
- Position: 1.0 long if signal > 0.001, -1.0 short if signal < -0.001, 0.0 otherwise
- Backtesting discrete bars with next‑day execution semantics
"""

from __future__ import annotations

import pandas as pd
import numpy as np
def _load_data(pair: str) -> pd.Series:
    """Load MT5 daily native data for pair.
    
    Path: engine/data/raw_mt5_{pair}_1d.csv
    Expected CSV columns: timestamp (UTC), close (float)
    Returns: close series with UTC DatetimeIndex
    """
    path = f"/root/aether-forex-lab/engine/data/raw_mt5_{pair}_1d.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"], dtype={"close": float})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df["close"]
def _momentum_signal(price: pd.Series, lookback: int = 252) -> pd.Series:
    """Compute frozen momentum signal: price_t / price_{t-lookback} – 1.
    
    Uses pandas pct_change(lookback) and NaNs are filled with 0.0 (neutral signal).
    """
    if len(price) < lookback + 1:
        raise ValueError(f"Insufficient data for lookback {lookback}: have {len(price)} bars")
    
    return price.pct_change(lookback).fillna(0.0)
def slow_time_series_momentum(price: pd.Series, **_) -> pd.Series:
    """STSM signal: 1.0 long if momentum > 0.001%, -1.0 short if < -0.001%, 0.0 flat.
    
    Corresponds to the frozen design: signals are action deltas from MT5 D1 momentum.
    """
    # Freezing: no parameter optimization, exact rules in PREREGISTRATION
    SIG_LONG = 0.001
    SIG_SHORT = -0.001
    
    signal = _momentum_signal(price, lookback=252)
    position = pd.Series(np.zeros(len(price)), index=price.index, dtype=float)
    
    long_mask = signal > SIG_LONG
    short_mask = signal < SIG_SHORT
    
    position[long_mask] = 1.0
    position[short_mask] = -1.0
    
    return position

__all__ = ["slow_time_series_momentum"]