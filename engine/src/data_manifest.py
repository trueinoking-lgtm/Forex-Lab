"""Market-data integrity manifest helpers."""
from __future__ import annotations
import hashlib, json, os, tempfile
import numpy as np
from pathlib import Path
import pandas as pd

INTERVALS = {"1d": pd.Timedelta(days=1), "1h": pd.Timedelta(hours=1),
             "30m": pd.Timedelta(minutes=30), "15m": pd.Timedelta(minutes=15)}


def normalize_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    out = df.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    duplicates = int(out.index.duplicated(keep="last").sum())
    return out[~out.index.duplicated(keep="last")].sort_index(), duplicates


def last_fully_closed(df, timeframe="1d", now=None):
    clean, _ = normalize_frame(df)
    if clean.empty: return None
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None: now = now.tz_localize("UTC")
    interval = INTERVALS[timeframe]
    closed = clean.index[clean.index + interval <= now]
    return closed[-1] if len(closed) else None


def is_cache_fresh(df, timeframe="1d", now=None, tolerance_intervals=2):
    last = last_fully_closed(df, timeframe, now)
    if last is None: return False
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None: now = now.tz_localize("UTC")
    return now - last <= INTERVALS[timeframe] * tolerance_intervals


def build_manifest(df, *, source, symbol, timeframe, download_ts=None,
                   provider_symbol=None, requested_start=None, requested_end=None,
                   timezone_before="unknown", transformations=None, software_version=None):
    clean, duplicates = normalize_frame(df)
    interval = INTERVALS[timeframe]
    diffs = clean.index.to_series().diff().dropna()
    gaps = [{"after": clean.index[i-1].isoformat(), "missing_intervals": int(delta / interval)-1}
            for i, delta in enumerate(diffs, 1) if delta > interval]
    hashed = hashlib.sha256(pd.util.hash_pandas_object(clean, index=True).values.tobytes()).hexdigest()
    last = last_fully_closed(clean, timeframe, download_ts)
    cols = {str(c).lower(): c for c in clean.columns}
    invalid = 0
    if all(k in cols for k in ("open", "high", "low", "close")):
        o,h,l,c = (pd.to_numeric(clean[cols[k]], errors="coerce") for k in ("open","high","low","close"))
        values = pd.concat([o,h,l,c], axis=1)
        invalid = int((~np.isfinite(values).all(axis=1) |
                       (h < pd.concat([o,c],axis=1).max(axis=1)) | (l > pd.concat([o,c],axis=1).min(axis=1)) |
                       (h < l) | (pd.concat([o,h,l,c],axis=1) <= 0).any(axis=1)).sum())
    return {"source": source, "symbol": symbol, "provider_symbol": provider_symbol or symbol,
            "timeframe": timeframe,
            "download_ts": pd.Timestamp(download_ts or pd.Timestamp.now(tz="UTC")).isoformat(),
            "retrieval_ts": pd.Timestamp(download_ts or pd.Timestamp.now(tz="UTC")).isoformat(),
            "requested_start": requested_start, "requested_end": requested_end,
            "first_candle": clean.index[0].isoformat() if len(clean) else None,
            "last_fully_closed_candle": last.isoformat() if last is not None else None,
            "row_count": len(clean), "duplicate_count": duplicates, "invalid_ohlc_count": invalid,
            "missing_interval_summary": {"gap_count": len(gaps), "gaps": gaps},
            "timezone_before": timezone_before, "timezone_after": "UTC", "timezone": "UTC",
            "transformation_steps": transformations or [], "software_version": software_version,
            "sha256_fingerprint": hashed}


def write_manifest(manifest, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w") as f: f.write(payload)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
