"""Fail-closed go/no-go report for demo-trading readiness."""
from __future__ import annotations

import math


def _finite(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def readiness_report(*, walk_forward_score, robustness, oos_return,
                     held_out_metrics: dict, directional_accuracy: dict,
                     max_drawdown_limit: float = 0.08,
                     min_profit_factor: float = 1.3,
                     min_directional_hit: float = 0.5,
                     regime_fit: bool = True) -> dict:
    held_out_metrics = held_out_metrics or {}
    directional_accuracy = directional_accuracy or {}
    wf, rob, oos = map(_finite, (walk_forward_score, robustness, oos_return))
    ho_ret = _finite(held_out_metrics.get("total_return"))
    dd = _finite(held_out_metrics.get("max_drawdown"))
    try:
        pf = float(held_out_metrics.get("profit_factor"))
        if math.isnan(pf):
            pf = None
    except (TypeError, ValueError):
        pf = None
    hit = _finite(directional_accuracy.get("hit_rate"))
    checks = {
        "walk_forward_score>=40": wf is not None and wf >= 40,
        "robustness>=0.3": rob is not None and rob >= 0.3,
        "oos_return>0": oos is not None and oos > 0,
        "held_out_return>0": ho_ret is not None and ho_ret > 0,
        "held_out_dd>=-limit": dd is not None and dd >= -max_drawdown_limit,
        "profit_factor>=1.3": pf is not None and pf >= min_profit_factor,
        "directional_hit>=0.5": hit is not None and hit >= min_directional_hit,
        "regime_fit": bool(regime_fit),
    }
    reasons = [f"{key}: {'OK' if passed else 'FAIL'}" for key, passed in checks.items()]
    return {"go": all(checks.values()), "reasons": reasons,
            "score": round(100 * sum(checks.values()) / len(checks), 1), "checks": checks}
