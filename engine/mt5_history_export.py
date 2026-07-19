#!/usr/bin/env python
"""Standalone read-only MT5 history exporter. Contains market-data calls only."""
from __future__ import annotations
import argparse, hashlib, re
from pathlib import Path
import pandas as pd
from run_acquire_data import atomic_csv
from src.data_manifest import build_manifest, normalize_frame, write_manifest

def sanitize(value):
    return re.sub(r"[^A-Za-z0-9 ._-]", "_", str(value or "unknown"))[:80]

def normalize_rates(rates, start, end):
    frame=pd.DataFrame(rates)
    required={"time","open","high","low","close"}
    if missing := required-set(frame): raise ValueError(f"MT5 rates missing fields: {sorted(missing)}")
    frame.index=pd.to_datetime(frame.pop("time"), unit="s", utc=True)
    frame.index.name="timestamp"
    if "tick_volume" in frame: frame=frame.rename(columns={"tick_volume":"volume"})
    if "volume" not in frame: frame["volume"]=0
    frame,_=normalize_frame(frame[["open","high","low","close","volume"]])
    return frame[(frame.index>=pd.Timestamp(start,tz="UTC")) & (frame.index<pd.Timestamp(end,tz="UTC"))]

def export(start="2010-01-01", end=None, output=None):
    try: import MetaTrader5 as mt5
    except ImportError as exc: raise RuntimeError("MetaTrader5 unavailable; run on the logged-in demo-terminal PC") from exc
    end=pd.Timestamp.now(tz="UTC").normalize() if end is None else pd.Timestamp(end,tz="UTC")
    if not mt5.initialize(): raise RuntimeError("MT5 terminal unavailable")
    try:
        terminal=mt5.terminal_info(); account=mt5.account_info()
        rates=mt5.copy_rates_range("EURUSD",mt5.TIMEFRAME_D1,pd.Timestamp(start,tz="UTC").to_pydatetime(),end.to_pydatetime())
        frame=normalize_rates(rates,start,end)
        if frame.empty: raise RuntimeError("MT5 returned no closed candles")
        path=Path(output or Path(__file__).parent/"data"/"raw_mt5_EURUSD_1d.csv"); atomic_csv(frame,path)
        manifest=build_manifest(frame,source="MetaTrader5 demo history",symbol="EURUSD",timeframe="1d",
          requested_start=start,requested_end=end.isoformat(),timezone_before="MT5 epoch seconds",
          transformations=["epoch seconds to UTC","sort/deduplicate","exclude incomplete candle"])
        manifest["broker"]={"company":sanitize(getattr(account,"company",None)),"server":sanitize(getattr(account,"server",None))}
        manifest["file_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest(); write_manifest(manifest,path.with_suffix(".manifest.json"))
        return path,manifest
    finally: mt5.shutdown()

def main():
    p=argparse.ArgumentParser(); p.add_argument("--start",default="2010-01-01"); p.add_argument("--end"); p.add_argument("--output")
    a=p.parse_args(); path,m=export(a.start,a.end,a.output); print(f"{path} rows={m['row_count']} sha256={m['file_sha256']}")
if __name__ == "__main__": main()
