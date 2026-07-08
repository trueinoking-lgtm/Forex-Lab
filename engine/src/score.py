"""Strategy scoring with overfitting / robustness penalty.

Composite score encodes the spec: return, drawdown, profit factor, win rate,
trade count, consistency, robustness.

Robustness penalty (the "penalize lucky periods" rule):
  - share_positive = fraction of walk-forward windows with positive return
  - oos_gap = clamp(in_sample_return / oos_return - 1, 0, 2)
  - robustness = share_positive * (1 - 0.5 * oos_gap)
  A strategy that wins in only ONE lucky window gets robustness ~0 and is
  down-weighted even if its headline return looks good.
"""
from __future__ import annotations
import numpy as np


# Composite weights (must sum to 1.0). Locked for v1.
WEIGHTS = {
    "return": 0.25,
    "sharpe": 0.20,
    "profit_factor": 0.20,
    "win_rate": 0.15,
    "trade_count": 0.05,
    "consistency": 0.10,
    "robustness": 0.05,
}


def _norm(x, lo, hi):
    if hi == lo:
        return 0.5
    return float(np.clip((x - lo) / (hi - lo), 0, 1))


def score_strategy(metrics: dict, window_returns: list[float],
                   in_sample_return: float, min_trades: int = 20) -> dict:
    """Return a score dict. metrics: walk-forward OOS metrics from backtest.
    window_returns: per-window OOS returns (for robustness)."""
    m = metrics
    trade_count = m.get("trade_count", 0)
    if trade_count < min_trades:
        return {"score": 0.0, "robustness": 0.0, "oos_gap": 0.0,
                "reason": f"insufficient trades ({trade_count}<{min_trades})", **{
                    k: m.get(k, float("nan")) for k in
                    ("total_return", "sharpe", "profit_factor", "win_rate", "max_drawdown")}}

    wins = [r for r in window_returns if r > 0]
    share_positive = len(wins) / len(window_returns) if window_returns else 0.0

    oos_ret = m.get("total_return", 0.0)
    if oos_ret > 0:
        oos_gap = float(np.clip(in_sample_return / oos_ret - 1, 0, 2))
    else:
        oos_gap = 1.0  # negative OOS => maximal gap penalty
    robustness = share_positive * (1 - 0.5 * oos_gap)

    # component subscores (0..1)
    s_return = _norm(oos_ret, -0.10, 0.20)
    s_sharpe = _norm(m.get("sharpe", 0), -0.5, 1.0)
    pf = m.get("profit_factor", float("nan"))
    s_pf = 0.0 if (pf != pf) else _norm(pf, 0.8, 2.0)
    s_wr = _norm(m.get("win_rate", 0), 0.4, 0.65)
    s_tc = _norm(trade_count, min_trades, 120)
    # consistency = low drawdown => high score
    s_cons = _norm(-m.get("max_drawdown", -1), -0.30, -0.02)
    s_rob = _norm(robustness, 0.2, 0.8)

    composite = (WEIGHTS["return"] * s_return + WEIGHTS["sharpe"] * s_sharpe +
                 WEIGHTS["profit_factor"] * s_pf + WEIGHTS["win_rate"] * s_wr +
                 WEIGHTS["trade_count"] * s_tc + WEIGHTS["consistency"] * s_cons +
                 WEIGHTS["robustness"] * s_rob)

    return {
        "score": round(composite * 100, 2),
        "robustness": round(robustness, 3),
        "oos_gap": round(oos_gap, 3),
        "share_positive_windows": round(share_positive, 3),
        "total_return": oos_ret, "sharpe": m.get("sharpe", 0.0),
        "profit_factor": pf, "win_rate": m.get("win_rate", 0.0),
        "max_drawdown": m.get("max_drawdown", 0.0),
        "trade_count": trade_count,
    }
