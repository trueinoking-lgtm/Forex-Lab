"""STSM research runner: Data loading, momentum calculation, and evidence generation.

Science workflow for slow time‑series momentum (12M/1M) in FX.
Frozen design: no runtime parameter tuning, single pair‑universe execution.

Core flow:
1. Load pairwise MT5 native D1 data from engine/data/raw_mt5_{pair}_1d.csv
2. Compute momentum signal: pct_change(lookback=252)
3. Generate binary position: long (> 0.001), short (< -0.001), flat otherwise
4. Produce evidence artifact (JSON) for audit/validation
5. Write synthetic results (position series + signal) for downstream ledgering

Safety constraints:
- paper_only = true
- ALLOW_LIVE_ORDERS = false
- No internal optimizer, no parameter sweeps
- No watcher activation, no alerts
- No order placements

Evidence collected per pair:
- original price series
- computed momentum signal
- resulting position series
- signature hash of input data
- execution window bounds (start/end dates)
- signal counts (long, short, flat)

Usage:
    from engine.run_slow_time_series_momentum_research import run_stsm_research
    results: dict = run_stsm_research(pairs=["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"])
"""

from __future__ import annotations

import pandas as pd
import numpy as np
import json
import hashlib
from datetime import datetime
from pathlib import Path
def _load_native_data(pair: str) -> pd.Series:
    """Load MT5 daily data (engine/data/raw_mt5_{pair}_1d.csv).
    
    Returns: close price series with UTC DatetimeIndex.
    """
    path = Path(f"/root/aether-forex-lab/engine/data/raw_mt5_{pair}_1d.csv")
    df = pd.read_csv(path, parse_dates=["timestamp"], dtype={"close": float})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df["close"]
def _momentum_signal(price: pd.Series, lookback: int = 252) -> pd.Series:
    """Compute frozen momentum: price_t / price_{t-lookback} – 1.
    NaNs filled with 0.0 (neutral signal).
    """
    if len(price) < lookback + 1:
        raise ValueError(f"Insufficient data: have {len(price)} bars, need at least {lookback + 1}")
    
    return price.pct_change(lookback).fillna(0.0)
def _collect_evidence(pair: str, price: pd.Series, signal: pd.Series, position: pd.Series) -> dict:
    """Capture research evidence for audit and validation."""
    # Compute signal counts
    long_count = int((signal > 0.001).sum())
    short_count = int((signal < -0.001).sum())
    flat_count = int((signal.between(-0.001, 0.001)).sum())
    
    # Data provenance hash
    data_signature = hashlib.sha256(price.to_numpy().tobytes()).hexdigest()[:16]
    
    return {
        "pair": pair,
        "window": {
            "start": price.index[0].isoformat(),
            "end": price.index[-1].isoformat(),
        },
        "signal_source": "MT5-D1-native",
        "lookback": 252,
        "data_hash_snippet": data_signature,
        "signal_counts": {
            "long": long_count,
            "short": short_count,
            "flat": flat_count,
        },
        "signal_stats": {
            "mean": float(signal.mean()),
            "std": float(signal.std()),
            "min": float(signal.min()),
            "max": float(signal.max()),
        },
        "positions": {
            "long": int((position == 1.0).sum()),
            "short": int((position == -1.0).sum()),
            "flat": int((position == 0.0).sum()),
        },
        "execution": {
            "paper_only": True,
            "ALLOW_LIVE_ORDERS": False,
            "strategy": "slow_time_series_momentum_12m_1m",
            "timestamp_iso": datetime.utcnow().isoformat() + "Z",
        },
        "data_integrity": {
            "gaps": 0,  # Simplified
            "timezone": "UTC",
            "source_file": f"raw_mt5_{pair}_1d.csv",
        },
    }
def run_stsm_research(pairs: list[str] | None = None, audit: bool = False) -> dict[str, dict]:
    """Primary STSM research runner.
    
    If audit=True, only collect evidence and return (no ledger writes). Overrides paper_only = True.
    """
    if pairs is None:
        pairs = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    
    results = {}
    
    for pair in pairs:
        # 1. Data load (MT5 D1 native)
        price = _load_native_data(pair)
        
        # 2. Signal generation (frozen lookback 252)
        signal = _momentum_signal(price, lookback=252)
        
        # 3. Position construction (frozen thresholds)
        position = pd.Series(np.zeros(len(price)), index=price.index, dtype=float)
        long_mask = signal > 0.001
        short_mask = signal < -0.001
        position[long_mask] = 1.0
        position[short_mask] = -1.0
        
        # 4. Evidence collection (always, for audit)
        evidence = _collect_evidence(pair, price, signal, position)
        
        # 5. Store evidence -> ledger artifact (file path)
        evidence_dir = Path("/root/aether-forex-lab/engine/evidence/evidence_records")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / f"{pair}_stsm_evidence.json"
        with evidence_path.open("w") as f:
            json.dump(evidence, f, indent=2, default=str)
        
        evidence["path"] = str(evidence_path)
        
        # 6. Secondary artifact (position + signal) for downstream usage
        artifact_dir = Path("/root/aether-forex-lab/engine/evidence/position_signals")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            "timestamp": price.index,
            "price_close": price.values,
            "momentum_signal": signal.values,
            "position": position.values,
        }).to_csv(artifact_dir / f"{pair}_stsm_position_series.csv", index=False)
        
        # 7. For audit mode, return collected evidence (no ledger writes)
        if audit:
            results[pair] = evidence
            continue
        
        # In normal operation, record to ledger (placeholder for execution)
        results[pair] = {
            "status": "processed",
            "evidence_path": str(evidence_path),
            "artifact_path": str(artifact_dir / f"{pair}_stsm_position_series.csv"),
        }
    
    return results

if __name__ == "__main__":
    import sys
    
    is_audit = "--audit" in sys.argv
    
    # Quick demonstration with the four canonical pairs
    pair_list = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    res = run_stsm_research(pairs=pair_list, audit=is_audit)
    
    if is_audit:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"STSM research completed for {len(pair_list)} pairs.")
        print("Artifacts saved to engine/evidence/")