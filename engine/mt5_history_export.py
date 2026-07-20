#!/usr/bin/env python
"""Standalone read-only MT5 history exporter.

Self-contained Windows-side tool. Uses ONLY the Python standard library,
pandas, and MetaTrader5. It contains no imports from engine-local modules
(run_acquire_data / src/*) so it runs unchanged on the Windows PC after a
plain copy.

Market-data calls only. Contains NO order imports or calls. Sanitizes broker
metadata and never prints account numbers or credentials. Normalizes timestamps
to UTC, excludes the incomplete current candle, writes atomically, and emits a
SHA-256 manifest.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, tempfile
from pathlib import Path

import pandas as pd


def sanitize(value):
    return re.sub(r"[^A-Za-z0-9 ._-]", "_", str(value or "unknown"))[:80]


def as_utc_timestamp(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def atomic_csv(frame, path):
    """Write a DataFrame atomically (temp file + fsync + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="") as f:
            frame.to_csv(f, index_label="timestamp")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def atomic_json(payload, path):
    """Write a JSON document atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload_str = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload_str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def normalize_frame(frame):
    """UTC-normalize, deduplicate (keep last), sort ascending."""
    out = frame.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    duplicates = int(out.index.duplicated(keep="last").sum())
    return out[~out.index.duplicated(keep="last")].sort_index(), duplicates


def build_manifest(frame, *, source, symbol, timeframe, download_ts=None,
                   requested_start=None, requested_end=None, timezone_before="unknown",
                   transformations=None, software_version=None):
    """Build a data-integrity manifest (no engine modules required)."""
    clean, duplicates = normalize_frame(frame)
    # interval for 1d
    interval = pd.Timedelta(days=1) if timeframe == "1d" else None
    diffs = clean.index.to_series().diff().dropna()
    gaps = []
    if interval is not None:
        for i, delta in enumerate(diffs, 1):
            if delta > interval:
                gaps.append({"after": clean.index[i - 1].isoformat(),
                             "missing_intervals": int(delta / interval) - 1})
    hashed = hashlib.sha256(clean.to_csv().encode("utf-8")).hexdigest()
    now = pd.Timestamp(download_ts or pd.Timestamp.now(tz="UTC"))
    last = clean.index[-1] if len(clean) else None
    return {
        "source": source, "symbol": symbol, "provider_symbol": symbol,
        "timeframe": timeframe,
        "download_ts": now.isoformat(),
        "retrieval_ts": now.isoformat(),
        "requested_start": requested_start, "requested_end": requested_end,
        "first_candle": clean.index[0].isoformat() if len(clean) else None,
        "last_fully_closed_candle": last.isoformat() if last is not None else None,
        "row_count": len(clean), "duplicate_count": duplicates,
        "missing_interval_summary": {"gap_count": len(gaps), "gaps": gaps},
        "timezone_before": timezone_before, "timezone_after": "UTC", "timezone": "UTC",
        "transformation_steps": transformations or [],
        "software_version": software_version,
        "sha256_fingerprint": hashed,
    }


def export(start="2010-01-01", end=None, output=None):
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 unavailable; run on the logged-in demo-terminal PC") from exc
    start_ts = as_utc_timestamp(start)
    end_ts = as_utc_timestamp(pd.Timestamp.now(tz="UTC").normalize() if end is None else end)
    if not mt5.initialize():
        raise RuntimeError("MT5 terminal unavailable")
    try:
        account = mt5.account_info()
        rates = mt5.copy_rates_range(
            "EURUSD", mt5.TIMEFRAME_D1,
            start_ts.to_pydatetime(), end_ts.to_pydatetime(),
        )
        frame = normalize_rates(rates, start_ts, end_ts)
        if frame.empty:
            raise RuntimeError("MT5 returned no closed candles")
        path = Path(output or Path(__file__).parent / "data" / "raw_mt5_EURUSD_1d.csv")
        atomic_csv(frame, path)
        manifest = build_manifest(
            frame, source="MetaTrader5 demo history", symbol="EURUSD", timeframe="1d",
            requested_start=start_ts.isoformat(), requested_end=end_ts.isoformat(),
            timezone_before="MT5 epoch seconds",
            transformations=["epoch seconds to UTC", "sort/deduplicate", "exclude incomplete candle"],
        )
        manifest["broker"] = {
            "company": sanitize(getattr(account, "company", None)),
            "server": sanitize(getattr(account, "server", None)),
        }
        manifest["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        atomic_json(manifest, path.with_suffix(".manifest.json"))
        return path, manifest
    finally:
        mt5.shutdown()


def normalize_rates(rates, start, end):
    """Convert MT5 rate tuples into a normalized, UTC-indexed OHLCV frame."""
    frame = pd.DataFrame(rates)
    required = {"time", "open", "high", "low", "close"}
    if missing := required - set(frame):
        raise ValueError(f"MT5 rates missing fields: {sorted(missing)}")
    frame.index = pd.to_datetime(frame.pop("time"), unit="s", utc=True)
    frame.index.name = "timestamp"
    if "tick_volume" in frame:
        frame = frame.rename(columns={"tick_volume": "volume"})
    if "volume" not in frame:
        frame["volume"] = 0
    frame = normalize_frame(frame[["open", "high", "low", "close", "volume"]])[0]
    start_ts = as_utc_timestamp(start)
    end_ts = as_utc_timestamp(end)
    return frame[(frame.index >= start_ts) & (frame.index < end_ts)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end")
    p.add_argument("--output")
    a = p.parse_args()
    path, m = export(a.start, a.end, a.output)
    print(f"{path} rows={m['row_count']} sha256={m['file_sha256']}")


if __name__ == "__main__":
    main()
