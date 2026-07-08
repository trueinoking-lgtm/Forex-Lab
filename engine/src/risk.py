"""Risk helpers (shared)."""
from __future__ import annotations
import numpy as np


def position_size(account: float, risk_pct: float, entry: float, stop_loss: float) -> float:
    risk_amt = account * float(np.clip(risk_pct, 0.5, 1.0)) / 100.0
    sl_dist = abs(entry - stop_loss)
    if sl_dist <= 0:
        raise ValueError("stop_loss must differ from entry")
    return risk_amt / sl_dist


def daily_pnl(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    return equity_curve[-1] - equity_curve[-2]
