"""Market Trend Intelligence — probabilistic regime + direction detection.

Research intelligence only. SAFETY: this module NEVER places a trade, never
computes order size, and never asserts certainty. Every output is probabilistic
and evidence-based; conflicting signals are labeled `uncertain`.

Design rules (v1.3 spec):
  - Regime in {trend, range, volatile, uncertain}
  - Direction in {bullish, bearish, sideways, uncertain}
  - Direction probabilities must sum to 1.0
  - When signals conflict (no clear winner / low trend strength + high vol),
    direction is forced to `uncertain`.
  - confidence is anchored to strategy history in similar regimes; with no
    history it is low and uncertainty is encouraged.
  - An invalidation price is always produced (required).
  - Language in `reasons`/`risks` is non-certain ("suggests", "possible").
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

# Wider than the signals REGIMES on purpose (trend-intel adds volatile/uncertain).
TREND_REGIMES = ("trend", "range", "volatile", "uncertain")
DIRECTIONS = ("bullish", "bearish", "sideways", "uncertain")

# Margin below which the top direction is not clearly ahead of the field.
UNCERTAINTY_GAP = 0.12


def _ema(price: pd.Series, span: int) -> pd.Series:
    return price.ewm(span=span, adjust=False).mean()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    prev = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev).abs(),
        (low - prev).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def classify_regime(close: pd.Series, high: pd.Series, low: pd.Series,
                    fast: int = 12, slow: int = 26, vol_window: int = 30,
                    vol_z: float = 2.0) -> dict:
    """Return regime + supporting scores. Evidence-based, no certainty."""
    if len(close) < max(slow, vol_window) + 5:
        return {
            "regime": "uncertain", "trend_strength": 0.0, "momentum_score": 0.0,
            "volatility_score": 0.5,
            "reasons": ["insufficient history to classify regime confidently"],
        }

    ef, es = _ema(close, fast), _ema(close, slow)
    atr_v = _atr(high, low, close)
    last = float(close.iloc[-1])

    # trend strength: normalized gap between fast/slow MA, scaled by ATR
    ma_gap = float((ef.iloc[-1] - es.iloc[-1]) / last)
    atr_pct = atr_v / last if last else 0.0
    # z-score of price vs slow MA (structure)
    slow_std = float(close.rolling(slow).std().iloc[-1])
    z_structure = (last - es.iloc[-1]) / slow_std if slow_std > 0 else 0.0
    trend_strength = float(np.clip(abs(z_structure) / 2.0, 0, 1))

    # momentum: ROC over fast window, normalized to [-1,1]
    roc = float((last - close.iloc[-fast]) / close.iloc[-fast]) if close.iloc[-fast] else 0.0
    momentum_score = float(np.clip(roc / (atr_pct * fast + 1e-9), -1, 1))

    # volatility: current ATR% vs rolling median (relative)
    atr_series = pd.concat([
        (high - low).abs(), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()
    ], axis=1).max(axis=1).rolling(14).mean() / close
    med = float(atr_series.rolling(vol_window).median().iloc[-1])
    vol_ratio = (atr_series.iloc[-1] / med) if med > 0 else 1.0
    volatility_score = float(np.clip((vol_ratio - 0.6) / (vol_z - 0.6), 0, 1))

    # regime selection
    reasons = []
    if volatility_score > 0.7 and trend_strength < 0.35:
        regime = "volatile"
        reasons.append(f"elevated volatility (ratio {vol_ratio:.2f}x median) with weak trend structure")
    elif trend_strength >= 0.45:
        regime = "trend"
        reasons.append(f"price {z_structure:+.2f}σ from slow MA, trend structure present")
    elif trend_strength < 0.2 and volatility_score < 0.45:
        regime = "range"
        reasons.append("price hugging slow MA, low directional structure")
    else:
        regime = "uncertain"
        reasons.append("mixed structure/volatility signals — no dominant regime")

    return {
        "regime": regime,
        "trend_strength": round(trend_strength, 4),
        "momentum_score": round(momentum_score, 4),
        "volatility_score": round(volatility_score, 4),
        "reasons": reasons,
    }


def score_directions(regime: str, trend_strength: float, momentum_score: float,
                     volatility_score: float) -> dict:
    """Probabilities for bullish/bearish/sideways, summing to 1.0.

    No certainty: even a strong trend keeps residual probability on the
    alternatives, and conflicting signals are pushed toward `uncertain`.
    """
    if regime == "uncertain":
        # spread mass roughly evenly; keep a small lean from momentum
        lean = 0.5 + 0.15 * momentum_score
        bull = lean * 0.5
        bear = (1 - lean) * 0.5
        side = 0.18
        return _normalize(bull, bear, side, uncertain=True)

    # base lean from momentum sign
    lean = 0.5 + 0.5 * momentum_score * (0.6 + 0.4 * trend_strength)
    bull = lean
    bear = 1 - lean
    side = (1 - trend_strength) * 0.35 + 0.05  # more sideways when weak trend

    d = _normalize(bull, bear, side, uncertain=False)
    # conflict rule: if the top direction is not clearly ahead, mark uncertain
    probs = {"bullish": d["bullish"], "bearish": d["bearish"], "sideways": d["sideways"]}
    top = max(probs.values())
    second = sorted(probs.values(), reverse=True)[1]
    if top - second < UNCERTAINTY_GAP or (trend_strength < 0.25 and volatility_score > 0.6):
        return _normalize(d["bullish"], d["bearish"], d["sideways"], uncertain=True)
    return d


def _normalize(bull: float, bear: float, side: float, uncertain: bool) -> dict:
    total = bull + bear + side
    if total <= 0:
        bull = bear = side = 1 / 3
        total = 1.0
    out = {
        "bullish": round(bull / total, 4),
        "bearish": round(bear / total, 4),
        "sideways": round(side / total, 4),
    }
    if uncertain:
        # fold probability mass into the uncertain bucket, keep directional
        # leans so the user still sees the bias
        keep = 0.45
        folded = (1 - keep)
        out = {k: round(v * keep, 4) for k, v in out.items()}
        out["uncertain"] = round(folded, 4)
    else:
        out["uncertain"] = 0.0
    return out


def dominant_direction(probs: dict) -> str:
    """Pick the label, preferring `uncertain` when it carries real mass."""
    if probs.get("uncertain", 0.0) >= 0.30:
        return "uncertain"
    ranked = sorted(((k, v) for k, v in probs.items() if k != "uncertain"),
                    key=lambda x: x[1], reverse=True)
    return ranked[0][0]


def assign_confidence(regime: str, direction: str, trend_strength: float,
                      momentum_score: float, volatility_score: float,
                      history: dict | None = None) -> tuple[float, str, list[str]]:
    """Confidence anchored to strategy history in similar regimes.

    history: optional {win_rate, robustness, sample} for the best strategy in a
    similar regime. With no history, confidence is low and uncertainty encouraged.
    Returns (confidence 0..1, best_strategy, risks).
    """
    risks: list[str] = []
    if history and history.get("sample", 0) >= 20:
        base = 0.30 + 0.50 * float(history["robustness"]) + 0.20 * float(history["win_rate"])
        best = history.get("strategy", "n/a")
    else:
        base = 0.20
        best = history.get("strategy", "n/a") if history else "n/a"
        risks.append("no comparable strategy history in a similar regime — low confidence")

    # discount for conflict / volatility
    if direction == "uncertain":
        base *= 0.6
        risks.append("conflicting signals — direction labeled uncertain by design")
    if volatility_score > 0.7:
        base *= 0.8
        risks.append("elevated volatility widens the likely error band")
    if trend_strength < 0.25:
        base *= 0.85
        risks.append("weak trend structure lowers conviction")

    conf = float(np.clip(base, 0.05, 0.95))
    return round(conf, 4), best, risks


def invalidation_price(direction: str, close: pd.Series, high: pd.Series,
                       low: pd.Series, mult: float = 1.5) -> float:
    """Required invalidation level. Always returned (never None).

    - bullish: recent swing low (structure break) below price
    - bearish: recent swing high above price
    - uncertain/sideways: nearest of the two, so either break invalidates
    """
    last = float(close.iloc[-1])
    atr_v = _atr(high, low, close)
    swing_lo = float(low.rolling(20).min().iloc[-1])
    swing_hi = float(high.rolling(20).max().iloc[-1])
    if direction == "bullish":
        lvl = min(swing_lo, last - mult * atr_v)
    elif direction == "bearish":
        lvl = max(swing_hi, last + mult * atr_v)
    else:
        # uncertain: tighter band — either side invalidates the no-clear-bias view
        lvl = min(swing_lo, last - mult * 0.5 * atr_v)
        lvl = max(lvl, last - 3 * atr_v)  # floor so it is never absurdly far
    return round(float(lvl), 5)


def build_snapshot(close: pd.Series, high: pd.Series, low: pd.Series,
                   symbol: str, timeframe: str, history: dict | None = None) -> dict:
    """Full probabilistic snapshot (research intelligence, no execution)."""
    rc = classify_regime(close, high, low)
    probs = score_directions(rc["regime"], rc["trend_strength"],
                             rc["momentum_score"], rc["volatility_score"])
    direction = dominant_direction(probs)
    conf, best, risks = assign_confidence(
        rc["regime"], direction, rc["trend_strength"], rc["momentum_score"],
        rc["volatility_score"], history)
    inv = invalidation_price(direction, close, high, low)

    reasons = list(rc["reasons"])
    ranked = sorted(((k, v) for k, v in probs.items()), key=lambda x: x[1], reverse=True)
    for k, v in ranked[:3]:
        if k != "uncertain":
            reasons.append(f"P({k})≈{v:.0%} (probabilistic estimate)")
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": rc["regime"],
        "direction": direction,
        "trend_strength": rc["trend_strength"],
        "momentum_score": rc["momentum_score"],
        "volatility_score": rc["volatility_score"],
        "confidence_score": conf,
        "best_strategy": best,
        "invalidation_price": inv,
        "probabilities": probs,
        "reasons": reasons,
        "risks": risks,
    }
