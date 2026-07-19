"""Single source of truth for research/watcher eligibility."""
from __future__ import annotations
import math
from . import backtest, score
from .trade_ledger import extract_trades, lifecycle_metrics

LOCKED_GATES = {"score": 40.0, "robustness": 0.3, "profit_factor": 1.3}


def gate_outcomes(values: dict, thresholds: dict | None = None) -> dict:
    t = {**LOCKED_GATES, **(thresholds or {})}
    def finite(name):
        try: return math.isfinite(float(values.get(name)))
        except (TypeError, ValueError): return False
    return {
        "score_gte_40": finite("score") and float(values["score"]) >= t["score"],
        "robustness_gte_0_3": finite("robustness") and float(values["robustness"]) >= t["robustness"],
        "oos_return_gt_0": finite("oos_return") and float(values["oos_return"]) > 0,
        "profit_factor_gte_1_3": finite("profit_factor") and float(values["profit_factor"]) >= t["profit_factor"],
    }


def evaluate_strategy_canonical(price, signal_fn, ctx, *, strategy, symbol,
                                params=None, spread_bps=2.0, slippage_bps=1.0,
                                commission_bps=0.0, thresholds=None):
    params = params or {}
    signal = signal_fn(price, **params)
    full = backtest.run(price, signal, ctx["cost_bps"], ctx["initial_capital"],
                        ctx["periods_per_year"], ctx["risk_free_rate"])
    wf = backtest.walk_forward(price, lambda p: signal_fn(p, **params), ctx)
    ledger = extract_trades(price, signal, strategy=strategy, symbol=symbol,
                            spread_bps=spread_bps, slippage_bps=slippage_bps,
                            commission_bps=commission_bps)
    life = lifecycle_metrics(ledger)
    scoring_metrics = dict(wf["metrics"])
    scoring_metrics.update({k: life[k] for k in ("trade_count", "win_rate")})
    scoring_metrics["profit_factor"] = (float("nan") if life["profit_factor"] is None
                                         else life["profit_factor"])
    sc = score.score_strategy(scoring_metrics, wf["window_returns"],
                              full["metrics"].get("total_return", 0.0),
                              min_trades=ctx.get("min_trades", 20))
    values = {**sc, "oos_return": wf["metrics"].get("total_return", 0.0),
              "profit_factor": life["profit_factor"]}
    gates = gate_outcomes(values, thresholds)
    reasons = [name for name, passed in gates.items() if not passed]
    return {"strategy": strategy, "parameters": params, "portfolio_metrics": wf["metrics"],
            "position_change_count": int(full["metrics"].get("trade_count", 0)),
            "lifecycle_metrics": life, "score": values["score"],
            "robustness": values["robustness"], "oos_return": values["oos_return"],
            "profit_factor": life["profit_factor"], "window_returns": wf["window_returns"],
            "gates": gates, "rejection_reasons": reasons,
            "eligible": all(gates.values()), "trades": ledger}
