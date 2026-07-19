"""Data ingestion. CSV import (v1-first) + optional yfinance (no key).

SAFETY: if market data fails to load, we RAISE — never fall back to fake data.
Demo/seed data must be explicitly labeled (is_demo=True) by the caller.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from .data_manifest import is_cache_fresh

try:
    import yfinance as yf
except ImportError:
    yf = None


def load_csv(path: str, is_demo: bool = False) -> pd.DataFrame:
    """Load OHLCV CSV. Columns: timestamp,open,high,low,close,volume.
    Raises if file missing or empty (no silent fallback)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"[DATA ERROR] CSV not found: {path} (no fake data used)")
    df = pd.read_csv(p)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"[DATA ERROR] CSV {path} missing columns: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df["is_demo"] = is_demo
    return df[["open", "high", "low", "close", "volume"]]


def fetch_yfinance(symbol: str, timeframe: str = "1d", lookback_days: int = 1095,
                   cache_dir: str = "data", start=None, end=None) -> pd.DataFrame:
    if yf is None:
        raise RuntimeError("[DATA ERROR] yfinance not installed (pip install yfinance)")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) / f"yf_{symbol.replace('/', '')}_{timeframe}.csv"
    if cache.exists() and start is None and end is None:
        cached = load_csv(str(cache))
        if is_cache_fresh(cached, timeframe):
            return cached
    end = pd.Timestamp.now(tz="UTC") if end is None else pd.Timestamp(end)
    if end.tzinfo is None: end = end.tz_localize("UTC")
    explicit_start = start is not None
    start = end - pd.Timedelta(days=lookback_days + 30) if start is None else pd.Timestamp(start)
    if start.tzinfo is None: start = start.tz_localize("UTC")
    raw = yf.download(symbol, start=start, end=end, interval=timeframe,
                      auto_adjust=True, progress=False)
    if raw is None or len(raw) == 0:
        if cache.exists() and is_cache_fresh(cached, timeframe):
            return cached
        raise RuntimeError(f"[DATA ERROR] yfinance returned no data for {symbol}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    if not explicit_start:
        df = df[df.index >= end - pd.Timedelta(days=lookback_days)]
    df.index.name = "timestamp"
    df.to_csv(cache)
    return df


def load_pair(symbol: str, source: str = "yfinance", csv_path: str | None = None,
              timeframe: str = "1d", lookback_days: int = 1095,
              cache_dir: str = "data", is_demo: bool = False) -> pd.DataFrame:
    if source == "csv":
        if csv_path is None:
            raise ValueError("[DATA ERROR] csv source requires csv_path")
        return load_csv(csv_path, is_demo=is_demo)
    return fetch_yfinance(symbol, timeframe, lookback_days, cache_dir)
