"""Performance metrics. Honest: computed on a chained out-of-sample equity curve."""
from __future__ import annotations
import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252,
                 risk_free: float = 0.0) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return (r.mean() - risk_free / periods_per_year) / r.std() * np.sqrt(periods_per_year)


def max_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def profit_factor(trade_returns: pd.Series | None) -> float:
    if trade_returns is None or len(trade_returns) == 0:
        return float("nan")
    wins = trade_returns[trade_returns > 0].sum()
    losses = -trade_returns[trade_returns < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else float("nan")
    return float(wins / losses)


def win_rate(trade_returns: pd.Series | None) -> float:
    if trade_returns is None or len(trade_returns) == 0:
        return 0.0
    return float((trade_returns > 0).mean())


def cagr(equity: pd.Series, periods_per_year: int = 252) -> float:
    if len(equity) < 2:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    yrs = len(equity) / periods_per_year
    if yrs <= 0 or total <= 0:
        return 0.0
    return float(total ** (1 / yrs) - 1)


def summary(equity: pd.Series, returns: pd.Series, trade_returns: pd.Series | None,
            periods_per_year: int = 252, risk_free: float = 0.0) -> dict:
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) else 0.0
    return {
        "total_return": total_return,
        "cagr": cagr(equity, periods_per_year),
        "sharpe": sharpe_ratio(returns, periods_per_year, risk_free),
        "max_drawdown": max_drawdown(equity),
        "profit_factor": profit_factor(trade_returns),
        "win_rate": win_rate(trade_returns),
        "trade_count": int(len(trade_returns)) if trade_returns is not None else 0,
        "final_equity": float(equity.iloc[-1]) if len(equity) else float("nan"),
    }


def buy_and_hold(price: pd.Series, initial_capital: float = 10000.0) -> pd.Series:
    return (price / price.iloc[0]) * initial_capital
