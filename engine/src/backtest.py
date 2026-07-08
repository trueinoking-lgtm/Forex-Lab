"""Honest backtester + walk-forward. No look-ahead; OOS windows chained.

walk_forward returns the chained OOS equity + metrics + per-window returns
(used by the robustness penalty in score.py).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .metrics import sharpe_ratio, max_drawdown, summary


def run(price: pd.Series, signal: pd.Series, cost_bps: float = 2.0,
        initial_capital: float = 10000.0, periods_per_year: int = 252,
        risk_free: float = 0.0) -> dict:
    cost = cost_bps / 10000.0
    pos = signal.shift(1).fillna(0.0).clip(-1, 1)      # act next bar
    ret = price.pct_change().fillna(0.0)
    strat = pos * ret
    change = pos.diff().abs().fillna(pos.abs())
    strat = strat - change * cost
    equity = (1 + strat).cumprod() * initial_capital
    trade_ret = strat[change > 0]
    return {"equity": equity, "returns": strat, "trade_returns": trade_ret,
            "metrics": summary(equity, strat, trade_ret, periods_per_year, risk_free)}


def _chain(all_ret, window_rets, all_trades, ic, pp, rf):
    if not all_ret:
        return {"equity": pd.Series([ic]), "returns": pd.Series([], dtype=float),
                "window_returns": [], "trade_returns": pd.Series([], dtype=float),
                "metrics": {}}
    chained = pd.concat(all_ret)
    equity = (1 + chained).cumprod() * ic
    trades = pd.concat(all_trades) if all_trades else pd.Series([], dtype=float)
    return {"equity": equity, "returns": chained, "window_returns": window_rets,
            "trade_returns": trades,
            "metrics": summary(equity, chained, trades, pp, rf)}


def walk_forward(price: pd.Series, signal_fn, ctx: dict) -> dict:
    """Proper walk-forward: signal computed over train+test (train history
    satisfies lookbacks), evaluate only the test portion. No future leakage."""
    wf = ctx["walk_forward"]
    train_d, test_d, step_d = wf["train_days"], wf["test_days"], wf["step_days"]
    cb, ic, pp, rf = ctx["cost_bps"], ctx["initial_capital"], ctx["periods_per_year"], ctx["risk_free_rate"]
    all_ret, window_rets, all_trades, start, n = [], [], [], 0, len(price)
    while start + train_d + test_d <= n:
        full = price.iloc[start:start + train_d + test_d]
        sig_full = signal_fn(full)
        test = full.iloc[train_d:]
        sig_test = sig_full.iloc[train_d:]
        res = run(test, sig_test, cb, ic, pp, rf)
        all_ret.append(res["returns"])
        window_rets.append(res["metrics"]["total_return"])
        if res["trade_returns"] is not None and len(res["trade_returns"]):
            all_trades.append(res["trade_returns"])
        start += step_d
    return _chain(all_ret, window_rets, all_trades, ic, pp, rf)


def walk_forward_bh(price: pd.Series, ctx: dict) -> dict:
    wf = ctx["walk_forward"]
    train_d, test_d, step_d = wf["train_days"], wf["test_days"], wf["step_days"]
    cb, ic, pp, rf = ctx["cost_bps"], ctx["initial_capital"], ctx["periods_per_year"], ctx["risk_free_rate"]
    cost = cb / 10000.0
    all_ret, window_rets, all_trades, start, n = [], [], [], 0, len(price)
    while start + train_d + test_d <= n:
        test = price.iloc[start + train_d:start + train_d + test_d]
        r = test.pct_change().fillna(0.0)
        charge = pd.Series(0.0, index=test.index)
        charge.iloc[0] = cost
        all_ret.append(r - charge)
        window_rets.append((r - charge).sum())
        start += step_d
    return _chain(all_ret, window_rets, [], ic, pp, rf)
