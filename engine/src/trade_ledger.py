"""Deterministic, research-only lifecycle trade extraction.

Signals observed at bar t become positions at t+1.  Prices are candle closes,
the same convention as :mod:`src.backtest`; this module has no execution API.
"""
from __future__ import annotations
import hashlib
import math
import pandas as pd


# Research-accounting convention.  Every pair receives the same account-currency
# notional; this is deliberately not broker contract/tick metadata.
ACCOUNT_CURRENCY = "USD"
SHARED_NOTIONAL = 100_000.0
PIP_SIZES = {"EURUSD": 0.0001, "GBPUSD": 0.0001,
             "AUDUSD": 0.0001, "USDJPY": 0.01}


def extract_trades(price: pd.Series, signal: pd.Series, *, strategy: str,
                   symbol: str, spread_bps: float = 0.0,
                   slippage_bps: float = 0.0, commission_bps: float = 0.0,
                   close_at_end: bool = False) -> list[dict]:
    price = price.astype(float).sort_index()
    signal = signal.reindex(price.index).fillna(0.0).clip(-1, 1)
    position = signal.shift(1).fillna(0.0)
    trades, opened = [], None

    def finish(i: int, reason: str, still_open: bool = False):
        nonlocal opened
        entry_i, direction, signal_i = opened
        ep, xp = float(price.iloc[entry_i]), float(price.iloc[i])
        price_change = direction * (xp - ep)
        gross_return = price_change / ep
        gross = gross_return * SHARED_NOTIONAL
        spread = SHARED_NOTIONAL * spread_bps / 10000.0
        slip = SHARED_NOTIONAL * slippage_bps / 10000.0
        commission = SHARED_NOTIONAL * commission_bps / 10000.0
        total = spread + slip + commission
        net = gross - total
        identity = f"{strategy}|{symbol}|{price.index[entry_i].isoformat()}|{direction}"
        trades.append({
            "trade_id": hashlib.sha256(identity.encode()).hexdigest()[:20],
            "strategy": strategy, "symbol": symbol,
            "direction": "long" if direction > 0 else "short",
            "signal_ts": price.index[signal_i].isoformat(),
            "entry_ts": price.index[entry_i].isoformat(), "entry_price": ep,
            "exit_ts": None if still_open else price.index[i].isoformat(),
            "exit_price": None if still_open else xp,
            "holding_bars": int(i - entry_i),
            "price_change": price_change,
            "gross_return": gross_return,
            "notional": SHARED_NOTIONAL,
            "account_currency": ACCOUNT_CURRENCY,
            "pip_size": PIP_SIZES.get(symbol),
            "price_change_pips": (price_change / PIP_SIZES[symbol]
                                  if symbol in PIP_SIZES else None),
            "gross_pnl": gross,
            "spread_cost": spread, "slippage_cost": slip,
            "commission": commission, "total_cost": total,
            "net_pnl": net,
            "return_pct": net / SHARED_NOTIONAL,
            "exit_reason": reason, "still_open_at_end": still_open,
        })
        opened = None

    prev = 0.0
    for i, raw in enumerate(position):
        cur = float(raw)
        if opened is not None and cur != prev:
            finish(i, "reversal" if cur and cur != prev else "signal_flat")
        if opened is None and cur and cur != prev:
            opened = (i, 1 if cur > 0 else -1, i - 1)
        prev = cur
    if opened is not None:
        if close_at_end:
            finish(len(price) - 1, "end_of_period")
        else:
            finish(len(price) - 1, "open_at_end", True)
    return trades


def lifecycle_metrics(trades: list[dict]) -> dict:
    closed = [t for t in trades if not t["still_open_at_end"]]
    pnl = [float(t["net_pnl"]) for t in closed]
    wins, losses = [x for x in pnl if x > 0], [x for x in pnl if x < 0]
    gp, gl = sum(wins), -sum(losses)
    streak_w = streak_l = max_w = max_l = 0
    for value in pnl:
        streak_w = streak_w + 1 if value > 0 else 0
        streak_l = streak_l + 1 if value < 0 else 0
        max_w, max_l = max(max_w, streak_w), max(max_l, streak_l)
    return {
        "trade_count": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "gross_profit": gp, "gross_loss": gl,
        "profit_factor": gp / gl if gl else (None if not gp else None),
        "avg_winner": sum(wins) / len(wins) if wins else 0.0,
        "avg_loser": sum(losses) / len(losses) if losses else 0.0,
        "expectancy": sum(pnl) / len(pnl) if pnl else 0.0,
        "avg_holding_time": (sum(t["holding_bars"] for t in closed) / len(closed)
                             if closed else 0.0),
        "largest_winner": max(wins, default=0.0), "largest_loser": min(losses, default=0.0),
        "largest_trade_gross_profit_pct": max(wins, default=0.0) / gp if gp else 0.0,
        "max_consecutive_wins": max_w, "max_consecutive_losses": max_l,
        "open_trade_count": len(trades) - len(closed),
    }
