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
    id: int | None = None   # DB row id (None when synthesized, e.g. backtest)

    def to_dict(self):
        return asdict(self)


@dataclass
class TradeGate:
    tradeable: bool
    reasons: list[str]


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


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """Return the latest Wilder Average Directional Index value."""
    if period <= 0:
        raise ValueError("period must be positive")
    high = pd.Series(high, dtype=float)
    low = pd.Series(low, dtype=float)
    close = pd.Series(close, dtype=float)
    if len(high) != len(low) or len(low) != len(close):
        raise ValueError("high, low, and close must have equal lengths")

    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Wilder smoothing is an EMA with alpha=1/period. ATR uses the same true
    # range definition as atr() above, but remains a series for DI calculation.
    smooth_tr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    smooth_plus = plus_dm.ewm(alpha=1 / period, adjust=False,
                              min_periods=period).mean()
    smooth_minus = minus_dm.ewm(alpha=1 / period, adjust=False,
                                min_periods=period).mean()
    plus_di = 100 * smooth_plus.div(smooth_tr.replace(0, np.nan))
    minus_di = 100 * smooth_minus.div(smooth_tr.replace(0, np.nan))
    di_sum = plus_di + minus_di
    dx = 100 * (plus_di - minus_di).abs().div(di_sum.replace(0, np.nan))
    # Once the initial DI smoothing exists, no directional movement is a real
    # DX of zero (not missing data). Preserve earlier NaNs so ADX itself still
    # requires a full second Wilder smoothing window.
    dx = dx.mask((di_sum == 0) & smooth_tr.notna(), 0.0)
    adx_series = dx.ewm(alpha=1 / period, adjust=False,
                        min_periods=period).mean()
    return float(adx_series.iloc[-1]) if len(adx_series) else float("nan")


def classify_regime(close: pd.Series, high: pd.Series, low: pd.Series,
                    period: int = 14) -> tuple[str, float]:
    adx_value = adx(high, low, close, period)
    if adx_value > 25:
        return "trend", adx_value
    if adx_value < 20:
        return "range", adx_value
    return "unknown", adx_value


def approve_for_trading(score: dict, robustness: float, oos_return: float,
                        strategy_preferred_regime: str, current_regime: str,
                        min_signal_score: float, min_robustness: float = 0.3,
                        min_profit_factor: float = 1.3) -> TradeGate:
    """Fail-closed walk-forward and regime approval gate."""
    reasons: list[str] = []

    def finite(value) -> bool:
        try:
            return bool(np.isfinite(float(value)))
        except (TypeError, ValueError):
            return False

    score_value = score.get("score") if isinstance(score, dict) else None
    profit_factor = score.get("profit_factor") if isinstance(score, dict) else None
    if not finite(score_value) or float(score_value) < min_signal_score:
        reasons.append(f"signal score must be >= {min_signal_score}")
    if not finite(robustness) or float(robustness) < min_robustness:
        reasons.append(f"robustness must be >= {min_robustness}")
    if not finite(oos_return) or float(oos_return) <= 0:
        reasons.append("OOS return must be positive")
    if not finite(profit_factor) or float(profit_factor) < min_profit_factor:
        reasons.append(f"profit factor must be >= {min_profit_factor}")
    regime_matches = (strategy_preferred_regime == "any" or
                      (current_regime != "unknown" and
                       strategy_preferred_regime == current_regime))
    if not regime_matches:
        reasons.append(
            f"preferred regime {strategy_preferred_regime!r} does not match "
            f"current regime {current_regime!r}"
        )
    return TradeGate(tradeable=not reasons, reasons=reasons)


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
