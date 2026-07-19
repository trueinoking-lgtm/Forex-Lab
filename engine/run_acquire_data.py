#!/usr/bin/env python
"""Deterministic, research-only EURUSD daily data acquisition."""
from __future__ import annotations
import argparse, hashlib, os, subprocess, tempfile
from pathlib import Path
import pandas as pd
from src.data import fetch_yfinance
from src.data_manifest import build_manifest, normalize_frame, write_manifest

ROOT = Path(__file__).parent

def latest_closed_day(now=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None: now = now.tz_localize("UTC")
    return now.normalize()

def atomic_csv(frame, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="."+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            frame.to_csv(f, index_label="timestamp"); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally: Path(tmp).unlink(missing_ok=True)

def acquire(start="2010-01-01", end=None, output=None):
    end_ts = latest_closed_day() if end is None else pd.Timestamp(end, tz="UTC")
    # yfinance end is exclusive; request through the cutoff then independently filter.
    frame = fetch_yfinance("EURUSD=X", "1d", cache_dir=str(ROOT/"data"),
                           start=start, end=end_ts + pd.Timedelta(days=1))
    frame, _ = normalize_frame(frame)
    frame = frame[(frame.index >= pd.Timestamp(start, tz="UTC")) & (frame.index < end_ts)]
    if frame.empty: raise RuntimeError("acquisition produced no fully closed candles")
    path = Path(output or ROOT/"data"/"raw_yfinance_EURUSD=X_1d.csv")
    atomic_csv(frame, path)
    try: git = subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT, text=True).strip()
    except Exception: git = "unknown"
    manifest = build_manifest(frame, source="yfinance", symbol="EURUSD", provider_symbol="EURUSD=X",
        timeframe="1d", requested_start=start, requested_end=end_ts.isoformat(),
        timezone_before="provider-naive daily labels", transformations=["auto_adjust=True", "normalize index UTC",
        "sort ascending", "deduplicate keep last", "exclude incomplete latest candle"],
        software_version={"git":git,"pandas":pd.__version__})
    manifest["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_manifest(manifest, path.with_suffix(".manifest.json"))
    return path, manifest

def main():
    p=argparse.ArgumentParser(); p.add_argument("--start",default="2010-01-01")
    p.add_argument("--end"); p.add_argument("--output"); a=p.parse_args()
    path,m=acquire(a.start,a.end,a.output)
    print(f"{path} rows={m['row_count']} sha256={m['file_sha256']}")
if __name__ == "__main__": main()
