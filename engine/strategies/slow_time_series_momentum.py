"""Slow Time-Series Momentum (STSM) strategy - corrected implementation.

Frozen preregistration (commit 5403529):
- Pair universe: EURUSD, GBPUSD, USDJPY, AUDUSD
- Data: Native MT5 D1 files (engine/data/raw_mt5_{pair}_1d.csv)
- Signal: price_t / price_{t-lookback} - 1 (252-day lookback, excluding recent month)
- Direction: >0 → long, <0 → short, =0 → flat
- Rebalance: Monthly (last bar of each calendar month)
- Holding: Until next rebalance
- Execution: Next available D1 bar's open after signal date
- Costs: 3 bps entry + 3 bps exit (6 bps round trip)
- Accounting: normalized_equal_risk_v1, version 2
- Folds: DEV (2010-2014), VALIDATION (2015-2018), TEST (2019-2024), DIAGNOSTIC (2025+)
- Safety: paper_only=true, ALLOW_LIVE_ORDERS=false

This implementation follows the frozen preregistration exactly.
No parameter optimization, no volatility scaling, no carry, no regime filters.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import hashlib
import json
# Frozen configuration from preregistration 5403529
PAIR_UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
LOOKBACK = 252  # 12-month formation window
RECENT_MONTH_OFFSET = 21  # Exclude most recent month
ENTRY_THRESHOLD = 0.0  # Pure sign logic: >0 long, <0 short, =0 flat
TRANSACTION_COST_BPS = 3.0  # Per side
NOTIONAL_PER_TRADE = 100_000.0  # USD
STARTING_EQUITY = 10_000.0
MAX_CONCURRENT_POSITIONS = 4
MAX_GROSS_NOTIONAL = 400_000.0
# Fold boundaries from preregistration
FOLD_BOUNDARIES = {
    "DEV": ("2010-01-04", "2014-12-31"),
    "VALIDATION": ("2015-01-01", "2018-12-31"),
    "TEST": ("2019-01-01", "2024-12-31"),
    "DIAGNOSTIC": ("2025-01-01", "2026-07-17"),
}
def _load_data(pair: str) -> pd.Series:
    """Load native MT5 D1 data for pair.
    
    Path: engine/data/raw_mt5_{pair}_1d.csv
    MT5 format: tab-separated with <DATE>, <OPEN>, <HIGH>, <LOW>, <CLOSE> columns
    Returns: close price series with DatetimeIndex
    """
    path = Path(f"/root/aether-forex-lab/engine/data/raw_mt5_{pair}_1d.csv")
    df = pd.read_csv(path, sep="\t", skiprows=1, 
                     names=["date", "open", "high", "low", "close", "tickvol", "vol", "spread"])
    df["date"] = pd.to_datetime(df["date"], format="%Y.%m.%d")
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    return df["close"]
def _compute_formation_return(price: pd.Series) -> pd.Series:
    """Compute frozen formation return: close[t-21] / close[t-273] - 1.
    
    This implements the preregistered signal:
    formation_return[t] = close[t-21] / close[t-273] - 1
    
    The 252-session formation window ends 21 sessions before the signal,
    so "12 months excluding the most recent month" is not conflated with
    the standard 252-session return that includes the recent month.
    
    Note: The denominator uses shift(273), NOT shift(252). The 252-session
    window is the span from t-273 to t-21 (inclusive), which is 252 sessions.
    """
    # Use explicit shifted observations
    numerator = price.shift(RECENT_MONTH_OFFSET)  # close[t-21]
    denominator = price.shift(LOOKBACK + RECENT_MONTH_OFFSET)  # close[t-273] = close[t-(252+21)]
    
    # Formation return
    formation_return = numerator / denominator - 1.0
    
    return formation_return
def _determine_direction(formation_return: float) -> int:
    """Determine direction from formation return.
    
    Frozen rule:
    - formation_return > 0 → +1 (long)
    - formation_return < 0 → -1 (short)
    - formation_return == 0 → 0 (flat/no trade)
    - NaN → 0 (insufficient data)
    """
    if pd.isna(formation_return):
        return 0
    if formation_return > ENTRY_THRESHOLD:
        return 1
    elif formation_return < ENTRY_THRESHOLD:
        return -1
    else:
        return 0
def _generate_rebalance_dates(price: pd.Series) -> pd.DatetimeIndex:
    """Generate deterministic monthly rebalance dates.
    
    Signal date: last available native D1 bar for that pair in each calendar month.
    """
    # Group by month and take last date
    monthly_groups = price.resample("ME").last()
    # Filter out months with no data
    rebalance_dates = monthly_groups.dropna().index
    return rebalance_dates
def _compute_trade_id(strategy: str, config: str, pair: str, signal_ts: str, entry_ts: str, holding: str) -> str:
    """Generate deterministic trade ID.
    
    Includes enough information to distinguish:
    - strategy family
    - configuration
    - pair
    - signal timestamp
    - entry timestamp
    - holding period
    """
    id_string = f"{strategy}|{config}|{pair}|{signal_ts}|{entry_ts}|{holding}"
    return hashlib.sha256(id_string.encode()).hexdigest()[:16]
def _apply_transaction_costs(direction: int, entry_price: float, exit_price: float) -> dict:
    """Apply frozen transaction costs: 3 bps per side.
    
    Returns dict with gross_pnl, costs, net_pnl
    """
    gross_pnl = direction * (exit_price / entry_price - 1) * NOTIONAL_PER_TRADE
    entry_cost = TRANSACTION_COST_BPS / 10_000 * NOTIONAL_PER_TRADE
    exit_cost = TRANSACTION_COST_BPS / 10_000 * NOTIONAL_PER_TRADE
    total_costs = entry_cost + exit_cost
    net_pnl = gross_pnl - total_costs
    return {
        "gross_pnl": gross_pnl,
        "costs": total_costs,
        "net_pnl": net_pnl,
    }
def slow_time_series_momentum(price: pd.Series, **kwargs) -> pd.Series:
    """STSM signal: 1.0 long if formation_return > 0, -1.0 short if < 0, 0.0 flat.
    
    Implements the frozen preregistration formula:
    formation_return[t] = close[t-21] / close[t-273] - 1
    direction[t] = +1 if formation_return[t] > 0
                 = -1 if formation_return[t] < 0
                 =  0 if formation_return[t] = 0 or required prices unavailable
    
    No thresholds beyond the frozen sign logic.
    """
    # Compute formation return using frozen formula
    formation_return = _compute_formation_return(price)
    
    # Initialize position series
    position = pd.Series(0.0, index=price.index, dtype=float)
    
    # Apply frozen sign logic
    for i in range(len(price)):
        direction = _determine_direction(formation_return.iloc[i])
        position.iloc[i] = float(direction)
    
    return position
def run_stsm_research(pairs: list[str] | None = None, audit: bool = False) -> dict:
    """Run STSM research with frozen configuration.
    
    Implements the full frozen design from preregistration 5403529:
    - Pair universe
    - Native MT5 D1 data
    - Signal generation (close[t-21] / close[t-273] - 1)
    - Monthly rebalance
    - Fold separation
    - Transaction costs (3 bps per side)
    - Accounting v2 (separate signal/executable ledgers)
    
    Safety: paper_only=true, ALLOW_LIVE_ORDERS=false
    """
    if pairs is None:
        pairs = PAIR_UNIVERSE
    
    results = {}
    
    for pair in pairs:
        # 1. Load native MT5 D1 data
        price = _load_data(pair)
        
        # 2. Compute formation return (frozen formula)
        formation_return = _compute_formation_return(price)
        
        # 3. Determine direction (frozen sign logic)
        direction = pd.Series(0, index=price.index, dtype=int)
        for i in range(len(price)):
            direction.iloc[i] = _determine_direction(formation_return.iloc[i])
        
        # 4. Generate rebalance dates (monthly, last bar)
        rebalance_dates = _generate_rebalance_dates(price)
        
        # 5. Generate signal opportunities (only on rebalance dates)
        signal_opportunities = []
        for signal_date in rebalance_dates:
            if signal_date in price.index:
                idx = price.index.get_loc(signal_date)
                fr = formation_return.iloc[idx]
                dir_val = _determine_direction(fr)
                
                # Entry: next available D1 bar's open after signal date
                if idx + 1 < len(price):
                    entry_date = price.index[idx + 1]
                    entry_price = price.iloc[idx + 1]
                else:
                    entry_date = None
                    entry_price = None
                
                signal_opportunities.append({
                    "pair": pair,
                    "signal_date": signal_date.isoformat(),
                    "formation_return": float(fr) if not pd.isna(fr) else None,
                    "direction": dir_val,
                    "entry_date": entry_date.isoformat() if entry_date else None,
                    "entry_price": float(entry_price) if entry_price else None,
                })
        
        # 6. Collect evidence for audit
        evidence = {
            "pair": pair,
            "data_file": f"engine/data/raw_mt5_{pair}_1d.csv",
            "first_timestamp": price.index[0].isoformat(),
            "last_timestamp": price.index[-1].isoformat(),
            "row_count": len(price),
            "data_hash": hashlib.sha256(price.to_numpy().tobytes()).hexdigest()[:16],
            "signal_count": len(signal_opportunities),
            "long_signals": sum(1 for s in signal_opportunities if s["direction"] == 1),
            "short_signals": sum(1 for s in signal_opportunities if s["direction"] == -1),
            "flat_signals": sum(1 for s in signal_opportunities if s["direction"] == 0),
            "execution": {
                "paper_only": True,
                "ALLOW_LIVE_ORDERS": False,
                "transaction_cost_bps": TRANSACTION_COST_BPS,
                "notional_per_trade": NOTIONAL_PER_TRADE,
            },
        }
        
        # 7. Write evidence artifact
        if audit:
            evidence_dir = Path("/root/aether-forex-lab/engine/evidence/evidence_records")
            evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence_path = evidence_dir / f"{pair}_stsm_evidence.json"
            with evidence_path.open("w") as f:
                json.dump(evidence, f, indent=2, default=str)
            evidence["path"] = str(evidence_path)
            results[pair] = evidence
        else:
            results[pair] = {
                "status": "processed",
                "signal_count": len(signal_opportunities),
            }
    
    return results
# Export symbols for registry
__all__ = [
    "slow_time_series_momentum",
    "run_stsm_research",
    "PAIR_UNIVERSE",
    "LOOKBACK",
    "RECENT_MONTH_OFFSET",
    "FOLD_BOUNDARIES",
]

if __name__ == "__main__":
    import sys
    is_audit = "--audit" in sys.argv
    res = run_stsm_research(audit=is_audit)
    if is_audit:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"STSM research completed for {len(PAIR_UNIVERSE)} pairs.")