"""Market-data integrity manifest helpers."""
from __future__ import annotations
import hashlib, json, os, tempfile
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


def build_manifest(df, *, source, symbol, timeframe, download_ts=None):
    clean, duplicates = normalize_frame(df)
    interval = INTERVALS[timeframe]
    diffs = clean.index.to_series().diff().dropna()
    gaps = [{"after": clean.index[i-1].isoformat(), "missing_intervals": int(delta / interval)-1}
            for i, delta in enumerate(diffs, 1) if delta > interval]
    hashed = hashlib.sha256(pd.util.hash_pandas_object(clean, index=True).values.tobytes()).hexdigest()
    last = last_fully_closed(clean, timeframe, download_ts)
    return {"source": source, "symbol": symbol, "timeframe": timeframe,
            "download_ts": pd.Timestamp(download_ts or pd.Timestamp.now(tz="UTC")).isoformat(),
            "first_candle": clean.index[0].isoformat() if len(clean) else None,
            "last_fully_closed_candle": last.isoformat() if last is not None else None,
            "row_count": len(clean), "duplicate_count": duplicates,
            "missing_interval_summary": {"gap_count": len(gaps), "gaps": gaps},
            "timezone": "UTC", "sha256_fingerprint": hashed}


def write_manifest(manifest, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w") as f: f.write(payload)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)

