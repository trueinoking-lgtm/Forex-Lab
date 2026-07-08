"""Signal scoring + risk gate for PAPER signals (v1, daily-close cadence).

SAFETY: this module NEVER places a trade. It only produces scored paper signals
and, when risk passes, a paper-trade *proposal* (JSON). Execution/live orders
are out of scope and blocked by paper_only in config.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, asdict
from .score import score_strategy

# Valid market regimes. A regime must be one of these; anything else fails loud
# so a typo like "grend" can never silently propagate into signals/reporting.
REGIMES = ("trend", "range")


def validate_regime(regime: str) -> str:
    if regime not in REGIMES:
        raise ValueError(
            f"Invalid regime {regime!r}; expected one of {REGIMES}. "
            f"Refusing to produce signals with an unknown regime."
        )
    return regime


@dataclass
class PaperSignal:
    pair: str
    strategy: str
    direction: int          # +1 long, -1 short
    entry: float
    stop_loss: float
    take_profit: float
    signal_score: float
    regime: str
    timestamp: str
    units: float = 0.0      # risk-sized position size from risk_check

    def to_dict(self):
        return asdict(self)


def compute_sl_tp(entry: float, direction: int, atr: float, sl_mult: float = 2.0,
                  tp_mult: float = 3.0) -> tuple[float, float]:
    if direction > 0:
        sl = entry - sl_mult * atr
        tp = entry + tp_mult * atr
    else:
        sl = entry + sl_mult * atr
        tp = entry - tp_mult * atr
    return round(sl, 5), round(tp, 5)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def score_signal(strategy_score: dict, regime: str, regime_allowed: bool) -> float:
    """Combine strategy composite with a regime check. If the regime gate says
    'do not trade this strategy now', the signal score is 0 (skip)."""
    base = strategy_score.get("score", 0.0)
    if not regime_allowed:
        return 0.0
    return round(base, 2)


def risk_check(account: float, risk_pct: float, entry: float, stop_loss: float) -> dict:
    """Risk 0.5-1% of simulated account per paper trade. Always requires SL."""
    risk_pct = float(np.clip(risk_pct, 0.5, 1.0))
    risk_amt = account * risk_pct / 100.0
    sl_dist = abs(entry - stop_loss)
    if sl_dist <= 0:
        return {"pass": False, "reason": "stop_loss == entry (no risk defined)"}
    units = risk_amt / sl_dist
    return {"pass": True, "risk_pct": risk_pct, "risk_amt": round(risk_amt, 2),
            "units": round(units, 2), "stop_loss": stop_loss, "take_profit": None}
