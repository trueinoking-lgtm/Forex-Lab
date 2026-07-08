"""Market universe + metadata for the multi-market research hub (v1.2).

A market is described by structured METADATA so the engine can apply the right
default cost model, session filter and data source per asset class:

  asset_class       : "forex" | "metal" | "crypto" | "index" | "equity"
  symbol            : instrument symbol (e.g. "EURUSD", "XAUUSD", "BTCUSD")
  session           : "fx_major" | "london" | "ny" | "24h" | "commodity"
  spread_model      : "fixed_bps" | "variable" | "commission"
  volatility_profile: "low" | "medium" | "high" | "extreme"
  data_source       : default yfinance ticker or "csv"
  default_spread_bps: typical round-trip spread in bps (used when re-scoring
                      external imports that arrive WITHOUT their own cost model)
  enabled           : whether the hub currently researches this market

IMPORTANT: external platforms (TradingView, trader.dev, generic backtests) are
IDEA SOURCES ONLY. Every imported result is RE-SCORED using OUR spread, slippage,
walk-forward and paper rules before it can enter the lab as a candidate. The lab
is always the source of truth. Paper-only. No live execution. No broker creds.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


ASSET_CLASSES = ("forex", "metal", "crypto", "index", "equity")
SESSIONS = ("fx_major", "london", "ny", "24h", "commodity")
SPREAD_MODELS = ("fixed_bps", "variable", "commission")
VOL_PROFILES = ("low", "medium", "high", "extreme")


# Default per-asset-class cost assumptions (round-trip bps) used ONLY when an
# imported result does not specify its own spread/slippage. These are research
# defaults, deliberately conservative; they are overridable per-import.
ASSET_CLASS_DEFAULTS = {
    "forex":  dict(spread_bps=2,   slippage_bps=1, vol="low",     session="fx_major",  spread_model="fixed_bps"),
    "metal":  dict(spread_bps=5,   slippage_bps=2, vol="medium",  session="commodity", spread_model="fixed_bps"),
    "crypto": dict(spread_bps=10,  slippage_bps=5, vol="high",    session="24h",       spread_model="variable"),
    "index":  dict(spread_bps=2,   slippage_bps=1, vol="medium",  session="london",    spread_model="fixed_bps"),
    "equity": dict(spread_bps=3,   slippage_bps=1, vol="medium",  session="ny",        spread_model="fixed_bps"),
}


@dataclass
class Market:
    symbol: str
    asset_class: str
    session: str
    spread_model: str
    volatility_profile: str
    data_source: str
    default_spread_bps: float
    name: str = ""
    enabled: bool = True
    default_slippage_bps: float = 1.0
    note: str = ""

    def to_dict(self):
        return asdict(self)


def validate_market(m: dict) -> dict:
    """Raise ValueError on any unknown enum value (fail-loud, no silent typo)."""
    for field_, allowed in (
        ("asset_class", ASSET_CLASSES), ("session", SESSIONS),
        ("spread_model", SPREAD_MODELS), ("volatility_profile", VOL_PROFILES),
    ):
        if m.get(field_) not in allowed:
            raise ValueError(
                f"Invalid market {field_}={m.get(field_)!r}; expected one of {allowed}")
    return m


# ---- Built-in universe (crypto research enabled later by flipping enabled) ----
_FOREX_MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD"]
_GOLD = ["XAUUSD"]


def _forex(sym: str) -> Market:
    d = ASSET_CLASS_DEFAULTS["forex"]
    return Market(symbol=sym, asset_class="forex", session=d["session"],
                  spread_model=d["spread_model"], volatility_profile=d["vol"],
                  data_source=f"{sym[:3]}={sym[3:]}",  # yfinance needs "EURUSD=X"
                  default_spread_bps=d["spread_bps"], default_slippage_bps=d["slippage_bps"],
                  name=f"{sym} FX Major", enabled=True)


def _gold() -> Market:
    d = ASSET_CLASS_DEFAULTS["metal"]
    return Market(symbol="XAUUSD", asset_class="metal", session=d["session"],
                  spread_model=d["spread_model"], volatility_profile=d["vol"],
                  data_source="GC=F", default_spread_bps=d["spread_bps"],
                  default_slippage_bps=d["slippage_bps"], name="Gold / USD", enabled=True)


def _crypto(sym: str) -> Market:
    """Crypto research MODE is present but DISABLED by default (research-later)."""
    d = ASSET_CLASS_DEFAULTS["crypto"]
    return Market(symbol=sym, asset_class="crypto", session=d["session"],
                  spread_model=d["spread_model"], volatility_profile=d["vol"],
                  data_source=f"{sym[:-3]}-USD", default_spread_bps=d["spread_bps"],
                  default_slippage_bps=d["slippage_bps"], name=f"{sym} Crypto",
                  enabled=False, note="crypto research mode — disabled until enabled")


UNIVERSE: list[Market] = (
    [_forex(s) for s in _FOREX_MAJORS]
    + [_gold()]
    + [_crypto("BTCUSD"), _crypto("ETHUSD")]   # present, disabled
)


def list_markets(asset_class: Optional[str] = None, only_enabled: bool = False) -> list[dict]:
    out = [m.to_dict() for m in UNIVERSE]
    if asset_class:
        out = [m for m in out if m["asset_class"] == asset_class]
    if only_enabled:
        out = [m for m in out if m["enabled"]]
    return out


def get_market(symbol: str) -> Market:
    for m in UNIVERSE:
        if m.symbol == symbol:
            return m
    raise KeyError(f"unknown market: {symbol}")


def universe_symbols(asset_class: Optional[str] = None, only_enabled: bool = True) -> list[str]:
    """Symbols the hub will actually research (default: enabled only)."""
    return [m["symbol"] for m in list_markets(asset_class, only_enabled)]
