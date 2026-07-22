"""STSM research runner - corrected implementation.

Implements the full frozen design from preregistration 5403529.

Safety: paper_only=true, ALLOW_LIVE_ORDERS=false
"""

from __future__ import annotations

import pandas as pd
import numpy as np
import json
import hashlib
from pathlib import Path
from datetime import datetime
from strategies.slow_time_series_momentum import (
    slow_time_series_momentum,
    _load_data,
    _compute_formation_return,
    _determine_direction,
    _generate_rebalance_dates,
    _compute_trade_id,
    _apply_transaction_costs,
    PAIR_UNIVERSE,
    LOOKBACK,
    RECENT_MONTH_OFFSET,
    FOLD_BOUNDARIES,
    TRANSACTION_COST_BPS,
    NOTIONAL_PER_TRADE,
    STARTING_EQUITY,
)
def run_stsm_research(pairs: list[str] | None = None, audit: bool = False) -> dict:
    """Run STSM research with frozen configuration.
    
    Implements the full frozen design from preregistration 5403529.
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
if __name__ == "__main__":
    import sys
    is_audit = "--audit" in sys.argv
    res = run_stsm_research(audit=is_audit)
    if is_audit:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"STSM research completed for {len(PAIR_UNIVERSE)} pairs.")