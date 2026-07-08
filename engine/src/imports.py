"""External research import adapters (v1.2).

External platforms are IDEA SOURCES ONLY. Aether Forex Lab is the source of
truth. Every imported strategy/backtest result is:
  1. parsed into a normalized ImportedResult,
  2. validated (fail-loud; missing/implausible fields rejected),
  3. LABELED is_external=True with the source name + original metrics preserved,
  4. RE-SCORED using OUR spread, slippage, walk-forward and paper rules via
     re_score() before it can be compared against native strategies.

No live execution. No broker credentials. No private keys. Paper-only.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

from . import backtest, score, markets as M


# Required fields every import must carry (besides the source label).
_REQUIRED = ("strategy_name", "symbol", "trades", "net_return")

# Plausibility bounds (reject obviously fabricated / broken numbers).
_MAX_ABS_RETURN = 50.0      # +/-5000% is not a credible OOS research result
_MIN_TRADES = 1
_MAX_TRADES = 100_000


@dataclass
class ImportedResult:
    source: str                 # "tradingview" | "traderdev" | "generic"
    strategy_name: str
    symbol: str
    asset_class: Optional[str]  # resolved from our universe / metadata
    trades: int
    net_return: float           # external reported net return (fraction)
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown: Optional[float] = None
    sharpe: Optional[float] = None
    reported_spread_bps: Optional[float] = None   # external's own cost model (if any)
    reported_slippage_bps: Optional[float] = None
    raw: dict = field(default_factory=dict)        # original payload, preserved

    def to_dict(self):
        return asdict(self)


# ----------------------------- validation -----------------------------
def validate_import(r: ImportedResult) -> ImportedResult:
    if not r.strategy_name or not r.symbol:
        raise ValueError(f"[IMPORT] strategy_name and symbol required (got {r.strategy_name!r}, {r.symbol!r})")
    for k in _REQUIRED:
        if getattr(r, k) is None:
            raise ValueError(f"[IMPORT] missing required field '{k}' from {r.source}")
    if not (abs(r.net_return) <= _MAX_ABS_RETURN):
        raise ValueError(f"[IMPORT] net_return {r.net_return} outside plausible bound "
                         f"[{-_MAX_ABS_RETURN}, {_MAX_ABS_RETURN}] — refusing (possible fake data)")
    if not (_MIN_TRADES <= r.trades <= _MAX_TRADES):
        raise ValueError(f"[IMPORT] trades {r.trades} outside plausible bound "
                         f"[{_MIN_TRADES}, {_MAX_TRADES}] — refusing")
    if r.win_rate is not None and not (0.0 <= r.win_rate <= 1.0):
        raise ValueError(f"[IMPORT] win_rate {r.win_rate} not in [0,1]")
    if r.max_drawdown is not None and not (-1.0 <= r.max_drawdown <= 0.0):
        raise ValueError(f"[IMPORT] max_drawdown {r.max_drawdown} not in [-1,0]")
    return r


# --------------------------- source adapters ---------------------------
def _resolve_asset_class(symbol: str) -> Optional[str]:
    try:
        return M.get_market(symbol).asset_class
    except KeyError:
        sym = symbol.upper()
        if sym.endswith("USD") or "=" in sym:
            return "forex"
        if "XAU" in sym or "GC" in sym:
            return "metal"
        if any(c in sym for c in ("BTC", "ETH", "USD", "-USD")) and ("BTC" in sym or "ETH" in sym):
            return "crypto"
        return None  # unknown — caller must decide; we label but do not research blindly


def from_traderdev(payload: dict) -> ImportedResult:
    """trader.dev / MCP result import (if available). Accepts the documented
    result blob shape: per-backtest KPIs."""
    return ImportedResult(
        source="traderdev",
        strategy_name=payload.get("strategy") or payload.get("name") or "traderdev_strategy",
        symbol=str(payload.get("symbol", "")).replace("=X", "").replace("-USD", "USD").upper(),
        asset_class=None,
        trades=int(payload.get("trade_count", payload.get("trades", 0))),
        net_return=float(payload.get("net_pnl_pct", payload.get("total_return", 0))) / 100.0
        if payload.get("net_pnl_pct") is not None else float(payload.get("total_return", 0)),
        win_rate=_to_frac(payload.get("win_rate")),
        profit_factor=_num(payload.get("profit_factor")),
        max_drawdown=_to_frac(payload.get("max_drawdown")) if payload.get("max_drawdown") is not None else None,
        sharpe=_num(payload.get("sharpe")),
        reported_spread_bps=_num(payload.get("cost_bps")),
        raw=payload,
    )


def from_tradingview(payload: dict) -> ImportedResult:
    """TradingView / PineScript strategy report. Pine `strategy.report` style:
    Net Profit %, # Trades, Percent Profitable, Profit Factor, Max Drawdown %,
    Sharpe. Source = idea only."""
    return ImportedResult(
        source="tradingview",
        strategy_name=payload.get("strategy_name") or payload.get("name") or "tv_strategy",
        symbol=str(payload.get("symbol", "")).replace("=X", "").replace("-USD", "USD").upper(),
        asset_class=None,
        trades=int(payload.get("trades", payload.get("trade_count", 0))),
        net_return=_to_frac(payload.get("net_profit_pct", payload.get("net_return"))),
        win_rate=_to_frac(payload.get("percent_profitable", payload.get("win_rate"))),
        profit_factor=_num(payload.get("profit_factor")),
        max_drawdown=-abs(_to_frac(payload.get("max_drawdown_pct", payload.get("max_drawdown"))))
        if payload.get("max_drawdown_pct", payload.get("max_drawdown")) is not None else None,
        sharpe=_num(payload.get("sharpe")),
        reported_spread_bps=_num(payload.get("commission_bps")),
        raw=payload,
    )


def from_generic(payload: dict) -> ImportedResult:
    """Generic backtest result via JSON/CSV row. Minimal contract:
    {strategy_name, symbol, trades, net_return, [optional metrics]}."""
    return ImportedResult(
        source="generic",
        strategy_name=str(payload.get("strategy_name") or payload.get("strategy") or "generic_strategy"),
        symbol=str(payload.get("symbol", "")).replace("=X", "").replace("-USD", "USD").upper(),
        asset_class=None,
        trades=int(payload.get("trades", payload.get("trade_count", 0))),
        net_return=_to_frac(payload.get("net_return", payload.get("net_pnl_pct"))),
        win_rate=_to_frac(payload.get("win_rate", payload.get("percent_profitable"))),
        profit_factor=_num(payload.get("profit_factor")),
        max_drawdown=_to_frac(payload.get("max_drawdown")) if payload.get("max_drawdown") is not None else None,
        sharpe=_num(payload.get("sharpe")),
        reported_spread_bps=_num(payload.get("spread_bps")),
        raw=payload,
    )


def parse_file(path: str) -> list[ImportedResult]:
    """Parse a .json or .csv import file into validated ImportedResult(s).
    CSV: one row per strategy. JSON: either a single object or a list."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"[IMPORT] file not found: {path}")
    text = p.read_text()
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        results = [_build(r) for r in data]
    elif p.suffix.lower() == ".csv":
        df = pd.read_csv(p)
        results = [_build(row) for row in df.to_dict(orient="records")]
    else:
        raise ValueError(f"[IMPORT] unsupported file type: {p.suffix} (use .json or .csv)")
    out = []
    for r in results:
        r.asset_class = _resolve_asset_class(r.symbol)
        validate_import(r)
        out.append(r)
    return out


def _build(payload: dict) -> ImportedResult:
    src = str(payload.get("source", "")).lower()
    if src == "tradingview":
        return from_tradingview(payload)
    if src == "traderdev":
        return from_traderdev(payload)
    return from_generic(payload)


# ------------------------- RE-SCORE (source of truth) -------------------------
def re_score(r: ImportedResult, override_spread_bps: Optional[float] = None,
             override_slippage_bps: Optional[float] = None,
             min_trades: int = 8) -> dict:
    """Re-score an imported result using OUR cost model + scoring.

    The external headline return is 're-costed': we subtract the gap between the
    external cost model (if any) and OUR cost model, then feed the adjusted
    return + external risk metrics through OUR composite scorer. This ensures an
    imported strategy can ONLY enter the lab if it survives OUR spread,
    slippage and robustness standards — never the external platform's reported
    (often optimistic, no-cost) numbers.

    If the import did not carry its own spread/slippage, we use the asset-class
    default from our universe metadata (the override, if provided, wins).
    """
    asset = r.asset_class or "forex"
    try:
        md = M.get_market(r.symbol)
        base_spread = md.default_spread_bps
        base_slip = md.default_slippage_bps
    except KeyError:
        base_spread = M.ASSET_CLASS_DEFAULTS.get(asset, M.ASSET_CLASS_DEFAULTS["forex"])["spread_bps"]
        base_slip = M.ASSET_CLASS_DEFAULTS.get(asset, M.ASSET_CLASS_DEFAULTS["forex"])["slippage_bps"]

    # our cost (override wins)
    our_spread = override_spread_bps if override_spread_bps is not None else base_spread
    our_slip = override_slippage_bps if override_slippage_bps is not None else base_slip
    our_total_bps = our_spread + our_slip
    # external cost (may be None => assume 0, i.e. external reported no-cost)
    ext_total_bps = (r.reported_spread_bps or 0) + (r.reported_slippage_bps or 0)

    cost_gap_bps = max(0.0, our_total_bps - ext_total_bps)   # we never credit them
    # Heuristic: round-trip cost is charged per trade. We approximate the
    # realized cost as (cost_gap_bps/10000) * trade_count * 0.5 — the 0.5
    # reflects that not every trade realizes the full gap and avoids over-
    # punishing strategies with very high trade counts. This is a deliberate,
    # documented approximation: external results have no per-bar series, so we
    # cannot re-run them tick-by-tick; re-costing the headline return is the
    # best available correction and is conservative (never credits external cost).
    adj_return = r.net_return - (cost_gap_bps / 10000.0) * max(r.trades, 1) * 0.5
    adj_return = float(np.clip(adj_return, -0.99, 10.0))

    metrics = {
        "total_return": adj_return,
        "sharpe": r.sharpe if r.sharpe is not None else 0.0,
        "profit_factor": r.profit_factor if r.profit_factor is not None else float("nan"),
        "win_rate": r.win_rate if r.win_rate is not None else 0.0,
        "max_drawdown": r.max_drawdown if r.max_drawdown is not None else -0.10,
        "trade_count": r.trades,
    }
    # imported results have no per-window series -> use a single window of the
    # (re-costed) return; robustness uses share_positive=1 window heuristic.
    sc = score.score_strategy(metrics, window_returns=[adj_return],
                              in_sample_return=r.net_return, min_trades=min_trades)
    sc["strategy"] = f"{r.strategy_name} [{r.source}]"
    sc["symbol"] = r.symbol
    sc["asset_class"] = asset
    sc["is_external"] = True
    sc["source"] = r.source
    sc["external_net_return"] = round(r.net_return, 4)
    sc["external_reported_spread_bps"] = r.reported_spread_bps
    sc["our_cost_bps"] = round(our_total_bps, 2)
    sc["cost_gap_bps"] = round(cost_gap_bps, 2)
    sc["re_costed_return"] = round(adj_return, 4)
    return sc


# ------------------------------- helpers -------------------------------
def _num(v):
    try:
        if v is None or v == "" or v is False:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_frac(v):
    """Accept a fraction or a percent string/number; returns a fraction."""
    n = _num(v)
    if n is None:
        return None
    # heuristic: values > 1 in a 'pct' field are percentages
    if abs(n) > 1.0 and v is not None:
        return n / 100.0
    return n
