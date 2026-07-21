"""Causal cross-sectional currency-strength research signals.

Every value at timestamp t is made only from returns ending at t.  A caller must
execute the resulting signal no earlier than the following bar's open.
"""
from __future__ import annotations

from collections.abc import Mapping
import numpy as np
import pandas as pd

PAIR_CURRENCIES = {
    "EURUSD": ("EUR", "USD"), "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"), "AUDUSD": ("AUD", "USD"),
}
CURRENCIES = ("EUR", "GBP", "USD", "JPY", "AUD")
METHODS = ("equal_weight", "vol_normalized", "ranked_momentum")
LOOKBACKS = (6, 12, 24, 48, 120)


def signed_currency_aggregation(pair_values: pd.DataFrame) -> pd.DataFrame:
    """Average pair observations with +base/-quote signs."""
    unknown = set(pair_values) - set(PAIR_CURRENCIES)
    if unknown:
        raise ValueError(f"unsupported pairs: {sorted(unknown)}")
    sums = pd.DataFrame(0.0, index=pair_values.index, columns=CURRENCIES)
    counts = {currency: 0 for currency in CURRENCIES}
    for pair in pair_values:
        base, quote = PAIR_CURRENCIES[pair]
        sums[base] = sums[base].add(pair_values[pair], fill_value=0)
        sums[quote] = sums[quote].sub(pair_values[pair], fill_value=0)
        counts[base] += 1; counts[quote] += 1
    for currency, count in counts.items():
        if count:
            sums[currency] /= count
        else:
            sums[currency] = np.nan
    return sums


def currency_strength(closes: pd.DataFrame, lookback: int,
                      method: str = "equal_weight") -> pd.DataFrame:
    """Return causal currency strengths for aligned close series."""
    if method not in METHODS or lookback not in LOOKBACKS:
        raise ValueError("method/lookback outside frozen preregistration")
    closes = closes.loc[:, list(PAIR_CURRENCIES)].astype(float).sort_index()
    returns = closes.pct_change(fill_method=None)
    cumulative = closes.pct_change(lookback, fill_method=None)
    if method == "vol_normalized":
        vol = returns.rolling(lookback, min_periods=lookback).std(ddof=0) * np.sqrt(lookback)
        pair_values = cumulative.div(vol.replace(0, np.nan)).clip(-10, 10)
    else:
        pair_values = cumulative
    strengths = signed_currency_aggregation(pair_values)
    if method == "ranked_momentum":
        strengths = strengths.rank(axis=1, pct=True, method="average").sub(0.2).div(0.8)
    return strengths.replace([np.inf, -np.inf], np.nan)


def construct_signals(closes: pd.DataFrame, lookback: int, method: str,
                      signal_filter: str = "continuation") -> pd.DataFrame:
    """One selected pair/direction per closed bar; execution is intentionally external."""
    if signal_filter not in ("continuation", "vol_filter", "trend_confirm"):
        raise ValueError("filter outside frozen preregistration")
    strengths = currency_strength(closes, lookback, method)
    diffs = pd.DataFrame({p: strengths[b] - strengths[q]
                          for p, (b, q) in PAIR_CURRENCIES.items()})
    selected = diffs.abs().idxmax(axis=1)
    out = pd.DataFrame(0, index=closes.index, columns=PAIR_CURRENCIES, dtype=np.int8)
    momentum = closes.pct_change(lookback, fill_method=None)
    hourly = closes.pct_change(fill_method=None)
    vol = hourly.rolling(lookback, min_periods=lookback).std(ddof=0)
    vol_median = vol.rolling(lookback, min_periods=lookback).median()
    for pair in PAIR_CURRENCIES:
        direction = np.sign(diffs[pair]).fillna(0).astype(np.int8)
        allowed = selected.eq(pair)
        if signal_filter == "vol_filter":
            allowed &= vol[pair] < vol_median[pair]
        elif signal_filter == "trend_confirm":
            allowed &= np.sign(momentum[pair]).eq(direction)
        out.loc[allowed, pair] = direction[allowed]
    return out


def currency_strength_signal(price: Mapping[str, pd.Series] | pd.DataFrame,
                             lookback: int = 24, method: str = "equal_weight",
                             signal_filter: str = "continuation", **_) -> pd.DataFrame:
    """Registry adapter for this multi-pair strategy family."""
    return construct_signals(pd.DataFrame(price), lookback, method, signal_filter)


def pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001


def pip_multiplier(pair: str) -> float:
    """Quote-price movement to pips (JPY pairs require the 100 multiplier)."""
    return 1.0 / pip_size(pair)
