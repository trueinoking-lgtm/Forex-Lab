"""Data ingestion. CSV import (v1-first) + optional yfinance (no key).

SAFETY: if market data fails to load, we RAISE — never fall back to fake data.
Demo/seed data must be explicitly labeled (is_demo=True) by the caller.
"""
from __future__ import annotations
from pathlib import Path
import os
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

# Allow optional API key via env (never logged, never required).
_YF_KEY = os.environ.get("YFINANCE_API_KEY", "")


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
                   cache_dir: str = "data") -> pd.DataFrame:
    if yf is None:
        raise RuntimeError("[DATA ERROR] yfinance not installed (pip install yfinance)")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) / f"yf_{symbol.replace('/', '')}_{timeframe}.csv"
    if cache.exists() and (pd.Timestamp.now(tz="UTC") - pd.to_datetime(
            pd.read_csv(cache, nrows=1)["timestamp"].iloc[0], utc=True)).days < 5:
        return load_csv(str(cache))
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=lookback_days + 30)
    raw = yf.download(symbol, start=start, end=end, interval=timeframe,
                      auto_adjust=True, progress=False)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"[DATA ERROR] yfinance returned no data for {symbol}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
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
