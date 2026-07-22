"""STSM executable portfolio accounting - Phase 1.

Implements the full trade lifecycle, separate ledgers, fixed-notional accounting,
fold isolation, canonical metrics, cost stress, and period/concentration checks.

Frozen preregistration (commit 5403529):
- Pair universe: EURUSD, GBPUSD, USDJPY, AUDUSD
- Signal: close[t-21] / close[t-273] - 1
- Direction: >0 long, <0 short, =0 flat
- Rebalance: Monthly (last bar)
- Holding: Until next rebalance
- Execution: Next available D1 bar's open after signal
- Costs: 3 bps per side
- Notional: USD 100,000 per accepted trade
- Starting equity: USD 10,000, no compounding
- Accounting: normalized_equal_risk_v1, version 2
- Folds: DEV/VALIDATION/TEST/DIAGNOSTIC
- Safety: paper_only=true, ALLOW_LIVE_ORDERS=false
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import hashlib
import json
from typing import Any
from strategies.slow_time_series_momentum import (
    PAIR_UNIVERSE,
    LOOKBACK,
    RECENT_MONTH_OFFSET,
    TRANSACTION_COST_BPS,
    NOTIONAL_PER_TRADE,
    STARTING_EQUITY,
    MAX_CONCURRENT_POSITIONS,
    MAX_GROSS_NOTIONAL,
    FOLD_BOUNDARIES,
    _load_data,
    _compute_formation_return,
    _determine_direction,
    _generate_rebalance_dates,
    _compute_trade_id,
    _apply_transaction_costs,
)

ACCOUNTING_VERSION = 2
ACCOUNTING_MODEL = "normalized_equal_risk_v1"
CONFIGURATION_ID = "stsm_12m_1m_v1"
HOLDING_PERIOD = "1M"  # Monthly holding period
def _load_ohlc_data(pair: str) -> pd.DataFrame:
    """Load native MT5 D1 data with OHLC columns.
    
    Returns DataFrame with open, high, low, close columns.
    """
    path = Path(f"/root/aether-forex-lab/engine/data/raw_mt5_{pair}_1d.csv")
    df = pd.read_csv(path, sep="\t", skiprows=1,
                     names=["date", "open", "high", "low", "close", "tickvol", "vol", "spread"])
    df["date"] = pd.to_datetime(df["date"], format="%Y.%m.%d")
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    return df
def _get_fold_for_timestamp(ts: pd.Timestamp) -> str | None:
    """Determine which fold a timestamp belongs to."""
    for fold_name, (start_str, end_str) in FOLD_BOUNDARIES.items():
        start = pd.Timestamp(start_str)
        end = pd.Timestamp(end_str)
        if start <= ts <= end:
            return fold_name
    return None
def _generate_signal_opportunities(pair: str, fold: str = "ALL") -> list[dict]:
    """Generate all signal opportunities for a pair.
    
    Returns list of signal opportunity dicts with:
    - trade_id
    - pair
    - configuration_id
    - direction
    - signal_timestamp
    - entry_timestamp
    - entry_price
    - exit_timestamp
    - exit_price
    - formation_return
    - unresolved (True if lifecycle incomplete within fold)
    
    Args:
        pair: Currency pair (e.g., "EURUSD")
        fold: Fold to filter by ("DEV", "VALIDATION", "TEST", "DIAGNOSTIC", "ALL")
    """
    price = _load_data(pair)
    ohlc = _load_ohlc_data(pair)
    formation_return = _compute_formation_return(price)
    rebalance_dates = _generate_rebalance_dates(price)
    
    # Determine fold boundaries
    if fold == "ALL":
        fold_start = price.index[0]
        fold_end = price.index[-1]
    else:
        fold_start_str, fold_end_str = FOLD_BOUNDARIES[fold]
        fold_start = pd.Timestamp(fold_start_str)
        fold_end = pd.Timestamp(fold_end_str)
    
    # Filter rebalance dates to fold
    fold_rebalance_dates = [rd for rd in rebalance_dates if fold_start <= rd <= fold_end]
    
    opportunities = []
    
    for signal_date in fold_rebalance_dates:
        if signal_date not in price.index:
            continue
        
        idx = price.index.get_loc(signal_date)
        fr = formation_return.iloc[idx]
        direction = _determine_direction(fr)
        
        # Skip flat signals (no trade opportunity)
        if direction == 0:
            continue
        
        # Entry: next available D1 bar after signal date
        if idx + 1 >= len(price):
            # Signal at final bar - no entry possible
            continue
        
        entry_idx = idx + 1
        entry_timestamp = price.index[entry_idx]
        
        # Entry must be within the fold
        if entry_timestamp > fold_end:
            continue  # Entry would fall in next fold - skip
        
        entry_price = ohlc.iloc[entry_idx]["open"]
        
        # Exit: next rebalance date after signal date, within the same fold
        # The exit must remain within the fold boundary
        next_rebalance = None
        for rd in fold_rebalance_dates:
            if rd > signal_date:
                next_rebalance = rd
                break
        
        if next_rebalance is None:
            # No next rebalance within fold - mark as unresolved
            # Do NOT fall back to global dataset end
            opportunities.append({
                "trade_id": _compute_trade_id(
                    "stsm", CONFIGURATION_ID, pair,
                    signal_date.isoformat(), entry_timestamp.isoformat(), HOLDING_PERIOD
                ),
                "pair": pair,
                "configuration_id": CONFIGURATION_ID,
                "direction": direction,
                "signal_timestamp": signal_date.isoformat(),
                "entry_timestamp": entry_timestamp.isoformat(),
                "entry_price": float(entry_price),
                "exit_timestamp": None,
                "exit_price": None,
                "formation_return": float(fr) if not pd.isna(fr) else None,
                "entry_idx": entry_idx,
                "exit_idx": None,
                "signal_idx": idx,
                "unresolved": True,
                "rejection_reason": "end_of_fold",
            })
            continue
        
        exit_idx = price.index.get_loc(next_rebalance)
        exit_timestamp = price.index[exit_idx]
        exit_price = ohlc.iloc[exit_idx]["open"]
        
        # If entry and exit are the same bar, skip (no holding period)
        if entry_idx == exit_idx:
            continue
        
        trade_id = _compute_trade_id(
            "stsm", CONFIGURATION_ID, pair,
            signal_date.isoformat(), entry_timestamp.isoformat(), HOLDING_PERIOD
        )
        
        opportunities.append({
            "trade_id": trade_id,
            "pair": pair,
            "configuration_id": CONFIGURATION_ID,
            "direction": direction,
            "signal_timestamp": signal_date.isoformat(),
            "entry_timestamp": entry_timestamp.isoformat(),
            "entry_price": float(entry_price),
            "exit_timestamp": exit_timestamp.isoformat(),
            "exit_price": float(exit_price),
            "formation_return": float(fr) if not pd.isna(fr) else None,
            "entry_idx": entry_idx,
            "exit_idx": exit_idx,
            "signal_idx": idx,
            "unresolved": False,
            "rejection_reason": None,
        })
    
    return opportunities
def _compute_trade_lifecycle(opportunity: dict, transaction_cost_bps: float = TRANSACTION_COST_BPS) -> dict:
    """Compute complete trade lifecycle for a signal opportunity.
    
    Returns dict with:
    - trade_id
    - pair
    - configuration_id
    - direction
    - signal_timestamp
    - entry_timestamp
    - exit_timestamp
    - entry_price
    - exit_price
    - gross_pnl
    - entry_cost
    - exit_cost
    - total_cost
    - net_pnl
    """
    direction = opportunity["direction"]
    entry_price = opportunity["entry_price"]
    exit_price = opportunity["exit_price"]
    
    # Gross PnL: direction * (exit/entry - 1) * notional
    gross_pnl = direction * (exit_price / entry_price - 1.0) * NOTIONAL_PER_TRADE
    
    # Costs: 3 bps per side
    entry_cost = transaction_cost_bps / 10_000 * NOTIONAL_PER_TRADE
    exit_cost = transaction_cost_bps / 10_000 * NOTIONAL_PER_TRADE
    total_cost = entry_cost + exit_cost
    
    net_pnl = gross_pnl - total_cost
    
    return {
        "trade_id": opportunity["trade_id"],
        "pair": opportunity["pair"],
        "configuration_id": opportunity["configuration_id"],
        "direction": direction,
        "signal_timestamp": opportunity["signal_timestamp"],
        "entry_timestamp": opportunity["entry_timestamp"],
        "exit_timestamp": opportunity["exit_timestamp"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_pnl": gross_pnl,
        "entry_cost": entry_cost,
        "exit_cost": exit_cost,
        "total_cost": total_cost,
        "net_pnl": net_pnl,
    }
def _run_portfolio_accounting(
    opportunities: list[dict],
    transaction_cost_bps: float = TRANSACTION_COST_BPS,
) -> dict:
    """Run chronological portfolio accounting.
    
    Processes trades in chronological order (by entry timestamp).
    Applies fixed-notional accounting with bankruptcy cutoff.
    
    Returns:
    - signal_ledger: list of all signal opportunity records
    - executable_ledger: list of accepted trade records
    - rejection_counts: dict of rejection reasons
    - metrics: dict of portfolio metrics
    """
    # Sort opportunities chronologically by entry timestamp
    # For simultaneous signals, sort by pair name (deterministic)
    sorted_ops = sorted(opportunities, key=lambda x: (x["entry_timestamp"], x["pair"]))
    
    # Initialize portfolio state
    equity = STARTING_EQUITY
    bankrupt = False
    bankruptcy_timestamp = None
    
    # Track open positions for concurrency check
    open_positions = {}  # pair -> exit_timestamp
    
    signal_ledger = []
    executable_ledger = []
    rejection_counts = {
        "bankruptcy": 0,
        "concurrency": 0,
        "invalid_data": 0,
        "final_cutoff": 0,
        "duplicate": 0,
        "end_of_fold": 0,
        "other": 0,
    }
    
    seen_trade_ids = set()
    
    for op in sorted_ops:
        trade_id = op["trade_id"]
        
        # Check for duplicate
        if trade_id in seen_trade_ids:
            rejection_counts["duplicate"] += 1
            signal_ledger.append({
                **op,
                "accepted_for_portfolio": False,
                "rejection_reason": "duplicate",
                "equity_before_entry": equity,
                "notional": NOTIONAL_PER_TRADE,
                "gross_pnl": 0.0,
                "total_cost": 0.0,
                "net_pnl": 0.0,
                "equity_after_exit": equity,
                "bankruptcy_state": bankrupt,
            })
            continue
        
        seen_trade_ids.add(trade_id)
        
        # Handle unresolved opportunities (end-of-fold, no exit available)
        if op.get("unresolved", False):
            rejection_counts["end_of_fold"] = rejection_counts.get("end_of_fold", 0) + 1
            signal_ledger.append({
                **op,
                "accepted_for_portfolio": False,
                "rejection_reason": "end_of_fold",
                "equity_before_entry": equity,
                "notional": NOTIONAL_PER_TRADE,
                "gross_pnl": 0.0,
                "total_cost": 0.0,
                "net_pnl": 0.0,
                "equity_after_exit": equity,
                "bankruptcy_state": bankrupt,
            })
            continue
        
        # Check bankruptcy
        if bankrupt:
            rejection_counts["bankruptcy"] += 1
            signal_ledger.append({
                **op,
                "accepted_for_portfolio": False,
                "rejection_reason": "bankruptcy",
                "equity_before_entry": 0.0,
                "notional": NOTIONAL_PER_TRADE,
                "gross_pnl": 0.0,
                "total_cost": 0.0,
                "net_pnl": 0.0,
                "equity_after_exit": 0.0,
                "bankruptcy_state": True,
            })
            continue
        
        # Check concurrency: max 4 concurrent positions
        entry_ts = pd.Timestamp(op["entry_timestamp"])
        exit_ts = pd.Timestamp(op["exit_timestamp"])
        
        # Remove closed positions
        pairs_to_remove = []
        for p, exit_t in open_positions.items():
            if exit_t <= entry_ts:
                pairs_to_remove.append(p)
        for p in pairs_to_remove:
            del open_positions[p]
        
        # Check if we have capacity
        if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
            rejection_counts["concurrency"] += 1
            signal_ledger.append({
                **op,
                "accepted_for_portfolio": False,
                "rejection_reason": "concurrency",
                "equity_before_entry": equity,
                "notional": NOTIONAL_PER_TRADE,
                "gross_pnl": 0.0,
                "total_cost": 0.0,
                "net_pnl": 0.0,
                "equity_after_exit": equity,
                "bankruptcy_state": bankrupt,
            })
            continue
        
        # Compute trade lifecycle
        lifecycle = _compute_trade_lifecycle(op, transaction_cost_bps)
        
        # Check for invalid data (NaN prices)
        if op["entry_price"] is None or op["exit_price"] is None:
            rejection_counts["invalid_data"] += 1
            signal_ledger.append({
                **op,
                "accepted_for_portfolio": False,
                "rejection_reason": "invalid_data",
                "equity_before_entry": equity,
                "notional": NOTIONAL_PER_TRADE,
                "gross_pnl": 0.0,
                "total_cost": 0.0,
                "net_pnl": 0.0,
                "equity_after_exit": equity,
                "bankruptcy_state": bankrupt,
            })
            continue
        
        # Accept trade
        equity_before = equity
        equity_after = equity + lifecycle["net_pnl"]
        
        # Check bankruptcy after this trade
        if equity_after <= 0:
            bankrupt = True
            bankruptcy_timestamp = op["entry_timestamp"]
            equity_after = 0.0
        
        # Add to open positions
        open_positions[op["pair"]] = exit_ts
        
        # Record in executable ledger
        executable_record = {
            "trade_id": lifecycle["trade_id"],
            "pair": lifecycle["pair"],
            "configuration_id": lifecycle["configuration_id"],
            "direction": lifecycle["direction"],
            "signal_timestamp": lifecycle["signal_timestamp"],
            "entry_timestamp": lifecycle["entry_timestamp"],
            "exit_timestamp": lifecycle["exit_timestamp"],
            "entry_price": lifecycle["entry_price"],
            "exit_price": lifecycle["exit_price"],
            "accepted_for_portfolio": True,
            "rejection_reason": None,
            "equity_before_entry": equity_before,
            "notional": NOTIONAL_PER_TRADE,
            "gross_pnl": lifecycle["gross_pnl"],
            "total_cost": lifecycle["total_cost"],
            "net_pnl": lifecycle["net_pnl"],
            "equity_after_exit": equity_after,
            "bankruptcy_state": bankrupt,
        }
        executable_ledger.append(executable_record)
        
        # Also record in signal ledger
        signal_ledger.append(executable_record)
        
        equity = equity_after
    
    # Handle unresolved end-of-data opportunities
    # (opportunities where entry_idx >= len(price) - already filtered out)
    
    # Compute metrics
    metrics = _compute_canonical_metrics(executable_ledger, equity, bankrupt, bankruptcy_timestamp)
    metrics["rejection_counts"] = rejection_counts
    metrics["generated_opportunities"] = len(opportunities)
    metrics["accepted_trades"] = len(executable_ledger)
    metrics["rejected_opportunities"] = len(signal_ledger) - len(executable_ledger)
    
    return {
        "signal_ledger": signal_ledger,
        "executable_ledger": executable_ledger,
        "rejection_counts": rejection_counts,
        "metrics": metrics,
        "equity": equity,
        "bankrupt": bankrupt,
        "bankruptcy_timestamp": bankruptcy_timestamp,
    }
def _compute_canonical_metrics(
    executable_ledger: list[dict],
    ending_equity: float,
    bankrupt: bool,
    bankruptcy_timestamp: str | None,
) -> dict:
    """Compute canonical portfolio metrics from accepted executable trades.
    
    Profit factor = combined gross profit / absolute combined gross loss
    """
    if not executable_ledger:
        return {
            "starting_equity": STARTING_EQUITY,
            "ending_equity": ending_equity,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "portfolio_return": -1.0 if bankrupt else 0.0,
            "max_drawdown": 1.0 if bankrupt else 0.0,
            "sharpe": 0.0,
            "robustness": 0.0,
            "score": 0.0,
            "long_count": 0,
            "short_count": 0,
            "long_pnl": 0.0,
            "short_pnl": 0.0,
            "trade_count": 0,
            "bankrupt": bankrupt,
            "bankruptcy_timestamp": bankruptcy_timestamp,
        }
    
    gross_profits = [t["gross_pnl"] for t in executable_ledger if t["gross_pnl"] > 0]
    gross_losses = [t["gross_pnl"] for t in executable_ledger if t["gross_pnl"] < 0]
    
    total_gross_profit = sum(gross_profits)
    total_gross_loss = sum(gross_losses)
    net_pnl = sum(t["net_pnl"] for t in executable_ledger)
    
    # Profit factor = combined gross profit / |combined gross loss|
    if abs(total_gross_loss) > 0:
        profit_factor = total_gross_profit / abs(total_gross_loss)
    else:
        profit_factor = float("inf") if total_gross_profit > 0 else 0.0
    
    trade_count = len(executable_ledger)
    expectancy = net_pnl / trade_count if trade_count > 0 else 0.0
    
    # Portfolio return
    if bankrupt:
        portfolio_return = -1.0
        max_drawdown = 1.0
    else:
        portfolio_return = (ending_equity - STARTING_EQUITY) / STARTING_EQUITY
        max_drawdown = _compute_max_drawdown(executable_ledger, STARTING_EQUITY)
    
    # Long/short breakdown
    long_trades = [t for t in executable_ledger if t["direction"] == 1]
    short_trades = [t for t in executable_ledger if t["direction"] == -1]
    long_pnl = sum(t["net_pnl"] for t in long_trades)
    short_pnl = sum(t["net_pnl"] for t in short_trades)
    
    # Sharpe (simplified: mean/std of trade returns)
    trade_returns = [t["net_pnl"] / NOTIONAL_PER_TRADE for t in executable_ledger]
    if len(trade_returns) > 1:
        mean_return = np.mean(trade_returns)
        std_return = np.std(trade_returns, ddof=1)
        sharpe = mean_return / std_return * np.sqrt(12) if std_return > 0 else 0.0
    else:
        sharpe = 0.0
    
    # Robustness (simplified)
    robustness = _compute_robustness(executable_ledger)
    
    # Score (simplified)
    score = profit_factor * (1 - max_drawdown) if not bankrupt else 0.0
    
    return {
        "starting_equity": STARTING_EQUITY,
        "ending_equity": ending_equity,
        "gross_profit": total_gross_profit,
        "gross_loss": total_gross_loss,
        "net_pnl": net_pnl,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "portfolio_return": portfolio_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "robustness": robustness,
        "score": score,
        "long_count": len(long_trades),
        "short_count": len(short_trades),
        "long_pnl": long_pnl,
        "short_pnl": short_pnl,
        "trade_count": trade_count,
        "bankrupt": bankrupt,
        "bankruptcy_timestamp": bankruptcy_timestamp,
    }
def _compute_max_drawdown(executable_ledger: list[dict], starting_equity: float, bankrupt: bool = False) -> float:
    """Compute maximum drawdown from chronological equity curve.
    
    Canonical drawdown is capped at 100% (0.0 to 1.0).
    For unfloored diagnostic, use _compute_max_drawdown_unfloored.
    """
    if bankrupt:
        return 1.0  # Bankrupt = 100% drawdown
    
    equity = starting_equity
    peak = starting_equity
    max_dd = 0.0
    
    for trade in executable_ledger:
        equity += trade["net_pnl"]
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
        else:
            dd = 1.0  # Equity at or below zero = 100% drawdown
        if dd > max_dd:
            max_dd = dd
    
    # Cap at 100%
    return min(max_dd, 1.0)
def _compute_max_drawdown_unfloored(executable_ledger: list[dict], starting_equity: float) -> float:
    """Compute unfloored maximum drawdown (for diagnostic only).
    
    This can exceed 100% when fixed notional causes losses beyond equity.
    """
    equity = starting_equity
    peak = starting_equity
    max_dd = 0.0
    
    for trade in executable_ledger:
        equity += trade["net_pnl"]
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
        else:
            dd = 1.0
        if dd > max_dd:
            max_dd = dd
    
    return max_dd
def _compute_robustness(executable_ledger: list[dict]) -> float:
    """Compute robustness score (simplified).
    
    Robustness is reduced if profitability depends on few trades.
    """
    if not executable_ledger:
        return 0.0
    
    trade_count = len(executable_ledger)
    # Simple robustness: higher trade count = more robust
    # Cap at 1.0 for 50+ trades
    return min(trade_count / 50.0, 1.0)
def _run_cost_stress(
    opportunities: list[dict],
    cost_levels: list[float] = None,
) -> dict:
    """Run cost stress tests at different transaction cost levels.
    
    Returns dict mapping cost level to metrics.
    """
    if cost_levels is None:
        cost_levels = [3.0, 5.0, 8.0, 12.0]  # bps per side
    
    results = {}
    
    for cost_bps in cost_levels:
        portfolio = _run_portfolio_accounting(opportunities, transaction_cost_bps=cost_bps)
        results[f"{cost_bps}bps"] = portfolio["metrics"]
    
    # Zero-cost diagnostic (non-canonical)
    zero_cost_portfolio = _run_portfolio_accounting(opportunities, transaction_cost_bps=0.0)
    results["zero_cost_non_canonical"] = zero_cost_portfolio["metrics"]
    
    # Removal of best trade
    if portfolio["executable_ledger"]:
        sorted_by_pnl = sorted(portfolio["executable_ledger"], key=lambda x: x["net_pnl"], reverse=True)
        best_trade_id = sorted_by_pnl[0]["trade_id"]
        filtered_ops = [op for op in opportunities if op["trade_id"] != best_trade_id]
        best_removed = _run_portfolio_accounting(filtered_ops)
        results["best_trade_removed"] = best_removed["metrics"]
        
        # Removal of best three trades
        best_three_ids = {t["trade_id"] for t in sorted_by_pnl[:3]}
        filtered_ops_3 = [op for op in opportunities if op["trade_id"] not in best_three_ids]
        best3_removed = _run_portfolio_accounting(filtered_ops_3)
        results["best_three_trades_removed"] = best3_removed["metrics"]
    
    return results
def _compute_period_concentration(executable_ledger: list[dict]) -> dict:
    """Compute period and concentration analysis.
    
    Returns performance by period, pair, and direction.
    """
    # Period analysis
    periods = {
        "2019-2020": {"start": "2019-01-01", "end": "2020-12-31"},
        "2021-2022": {"start": "2021-01-01", "end": "2022-12-31"},
        "2023-2024": {"start": "2023-01-01", "end": "2024-12-31"},
    }
    
    period_results = {}
    for period_name, bounds in periods.items():
        period_trades = [
            t for t in executable_ledger
            if bounds["start"] <= t["entry_timestamp"][:10] <= bounds["end"]
        ]
        if period_trades:
            period_pnl = sum(t["net_pnl"] for t in period_trades)
            period_results[period_name] = {
                "trade_count": len(period_trades),
                "net_pnl": period_pnl,
            }
        else:
            period_results[period_name] = {"trade_count": 0, "net_pnl": 0.0}
    
    # Pair contribution
    pair_results = {}
    for pair in PAIR_UNIVERSE:
        pair_trades = [t for t in executable_ledger if t["pair"] == pair]
        if pair_trades:
            pair_pnl = sum(t["net_pnl"] for t in pair_trades)
            pair_results[pair] = {
                "trade_count": len(pair_trades),
                "net_pnl": pair_pnl,
            }
        else:
            pair_results[pair] = {"trade_count": 0, "net_pnl": 0.0}
    
    # Direction contribution
    long_trades = [t for t in executable_ledger if t["direction"] == 1]
    short_trades = [t for t in executable_ledger if t["direction"] == -1]
    
    direction_results = {
        "long": {
            "trade_count": len(long_trades),
            "net_pnl": sum(t["net_pnl"] for t in long_trades),
        },
        "short": {
            "trade_count": len(short_trades),
            "net_pnl": sum(t["net_pnl"] for t in short_trades),
        },
    }
    
    # Best/worst trade contributions
    if executable_ledger:
        sorted_by_pnl = sorted(executable_ledger, key=lambda x: x["net_pnl"], reverse=True)
        best_trade = sorted_by_pnl[0]
        worst_trade = sorted_by_pnl[-1]
        
        best_three = sorted_by_pnl[:3]
        best_three_pnl = sum(t["net_pnl"] for t in best_three)
        
        best_pair = max(pair_results.items(), key=lambda x: x[1]["net_pnl"])
        worst_pair = min(pair_results.items(), key=lambda x: x[1]["net_pnl"])
        
        concentration = {
            "best_trade_contribution": best_trade["net_pnl"],
            "best_trade_id": best_trade["trade_id"],
            "best_three_contribution": best_three_pnl,
            "best_pair": best_pair[0],
            "best_pair_pnl": best_pair[1]["net_pnl"],
            "worst_pair": worst_pair[0],
            "worst_pair_pnl": worst_pair[1]["net_pnl"],
        }
    else:
        concentration = {
            "best_trade_contribution": 0.0,
            "best_trade_id": None,
            "best_three_contribution": 0.0,
            "best_pair": None,
            "best_pair_pnl": 0.0,
            "worst_pair": None,
            "worst_pair_pnl": 0.0,
        }
    
    return {
        "periods": period_results,
        "pairs": pair_results,
        "directions": direction_results,
        "concentration": concentration,
    }
def _filter_opportunities_by_fold(
    opportunities: list[dict],
    fold: str,
) -> list[dict]:
    """Filter opportunities by fold."""
    start_str, end_str = FOLD_BOUNDARIES[fold]
    start = pd.Timestamp(start_str)
    end = pd.Timestamp(end_str)
    
    return [
        op for op in opportunities
        if start <= pd.Timestamp(op["entry_timestamp"]) <= end
    ]
def _persist_ledgers(
    signal_ledger: list[dict],
    executable_ledger: list[dict],
    output_dir: str = "/root/aether-forex-lab/engine/evidence/portfolio_ledgers",
):
    """Persist signal and executable ledgers to disk."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Signal opportunity ledger
    signal_path = output_path / "signal_opportunity_ledger.json"
    with signal_path.open("w") as f:
        json.dump(signal_ledger, f, indent=2, default=str)
    
    # Executable portfolio ledger
    exec_path = output_path / "executable_portfolio_ledger.json"
    with exec_path.open("w") as f:
        json.dump(executable_ledger, f, indent=2, default=str)
    
    return str(signal_path), str(exec_path)
def run_stsm_portfolio_accounting(audit: bool = False) -> dict:
    """Run full STSM portfolio accounting.
    
    Implements:
    - Trade lifecycle (signal → entry → exit)
    - Separate signal/executable ledgers
    - Fixed-notional accounting (USD 100,000 per trade)
    - Fold isolation
    - Canonical metrics (TEST fold)
    - Cost stress
    - Period/concentration analysis
    
    Safety: paper_only=true, ALLOW_LIVE_ORDERS=false
    """
    # 1. Generate all signal opportunities with fold-specific lifecycle
    all_opportunities = []
    for pair in PAIR_UNIVERSE:
        opps = _generate_signal_opportunities(pair, fold="ALL")
        all_opportunities.extend(opps)
    
    # 2. Run portfolio accounting (full history)
    portfolio = _run_portfolio_accounting(all_opportunities)
    
    # 3. Generate TEST fold opportunities with TEST fold boundaries
    test_opportunities = []
    for pair in PAIR_UNIVERSE:
        opps = _generate_signal_opportunities(pair, fold="TEST")
        test_opportunities.extend(opps)
    test_portfolio = _run_portfolio_accounting(test_opportunities)
    
    # 4. Cost stress
    cost_stress = _run_cost_stress(all_opportunities)
    
    # 5. Period/concentration
    period_concentration = _compute_period_concentration(portfolio["executable_ledger"])
    
    # 6. Persist ledgers
    if audit:
        signal_path, exec_path = _persist_ledgers(
            portfolio["signal_ledger"],
            portfolio["executable_ledger"],
        )
    else:
        signal_path = None
        exec_path = None
    
    # 7. Reconciliation check
    generated = len(all_opportunities)
    accepted = len(portfolio["executable_ledger"])
    rejected = generated - accepted
    
    result = {
        "accounting": {
            "model": ACCOUNTING_MODEL,
            "version": ACCOUNTING_VERSION,
            "configuration_id": CONFIGURATION_ID,
            "policy": "fixed_notional_fixed_exposure",
            "notional_per_trade": NOTIONAL_PER_TRADE,
            "starting_equity": STARTING_EQUITY,
            "no_compounding": True,
            "paper_only": True,
            "ALLOW_LIVE_ORDERS": False,
        },
        "portfolio": {
            "generated_opportunities": generated,
            "accepted_trades": accepted,
            "rejected_opportunities": rejected,
            "rejection_counts": portfolio["rejection_counts"],
            "equity": portfolio["equity"],
            "bankrupt": portfolio["bankrupt"],
            "bankruptcy_timestamp": portfolio["bankruptcy_timestamp"],
            "metrics": portfolio["metrics"],
        },
        "test_fold": {
            "generated_opportunities": len(test_opportunities),
            "accepted_trades": len(test_portfolio["executable_ledger"]),
            "rejected_opportunities": len(test_opportunities) - len(test_portfolio["executable_ledger"]),
            "metrics": test_portfolio["metrics"],
        },
        "cost_stress": cost_stress,
        "period_concentration": period_concentration,
        "ledgers": {
            "signal_opportunity_ledger_path": signal_path,
            "executable_portfolio_ledger_path": exec_path,
        },
    }
    
    return result
# Export symbols
__all__ = [
    "run_stsm_portfolio_accounting",
    "ACCOUNTING_VERSION",
    "ACCOUNTING_MODEL",
    "CONFIGURATION_ID",
    "HOLDING_PERIOD",
    "STARTING_EQUITY",
    "NOTIONAL_PER_TRADE",
    "FOLD_BOUNDARIES",
]

if __name__ == "__main__":
    import sys
    is_audit = "--audit" in sys.argv
    res = run_stsm_portfolio_accounting(audit=is_audit)
    print(json.dumps(res, indent=2, default=str))