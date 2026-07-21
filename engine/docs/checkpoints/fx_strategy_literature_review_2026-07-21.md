# FX Strategy Literature Review & Shortlist

**Date:** 2026-07-21
**Phase:** Phase 2 — pre-backtest literature review (currency_strength family is REJECTED & CLOSED)
**Status:** RESEARCH ONLY — no implementation, no backtest yet.
**Objective:** survey ~10 documented FX effects from academic / BIS / NBER / central-bank / established quant literature, then rank and recommend 2–3 candidates for preregistration.

Current available data: MT5 H1 (and D1) for EURUSD, GBPUSD, USDJPY, AUDUSD (limited USD-hub universe, 2010-01-04 → 2026-07-17). Any candidate needing a wider cross-section or interest-rate / macro data is flagged for **additional data needed**.

---

## Shortlist (ranked)

| # | Candidate | Priority | Best-fit with current data |
|---|-----------|----------|----------------------------|
| 1 | Slow time-series momentum (12M/1M) | HIGH | Medium — needs long history (have D1 from 2010) |
| 2 | Carry | MEDIUM-HIGH | Low — needs interest-rate differentials (NOT in MT5 price data) |
| 3 | Carry + trend filter | MEDIUM-HIGH | Low — same data gap + needs trend signal |
| 4 | Cross-sectional momentum | HIGH | Medium — needs >4 pairs for a real cross-section |
| 5 | Value / PPP | MEDIUM | Low — needs PPP/real-rate macro data |
| 6 | Volatility-managed momentum | HIGH | Medium — needs vol estimate (H1 ok) |
| 7 | Defensive risk-off filter | MEDIUM | Medium — VIX/risk proxy needed |
| 8 | Multi-factor carry/value/momentum | MEDIUM | Low — needs all three inputs |
| 9 | Seasonality (month/quarter-end) | LOW-MEDIUM | Low — thin academic evidence |
| 10 | Carry + vol-managed momentum | MEDIUM-HIGH | Low/Medium — needs rates + vol |

---

## Candidate details

### 1. Slow time-series momentum (FX)
- **Source:** Menkhoff, Sarno, Schmeling & Schrimpf (2012), *Currency Momentum Strategies*, JFE 106(3):660–684; Asness, Moskowitz & Pedersen (2013), *Value and Momentum Everywhere*, JFE 68(3); Okunev & White (2003).
- **Rationale:** Currencies that appreciated most over the past 12 months tend to keep appreciating (positive autocorrelation in forward premia / exposure to global risk factors).
- **Timeframe:** Monthly rebalance; lookback ~12 months, skip most recent 1 month.
- **Data:** Monthly (or daily) FX vs USD, broad G10+. **Markets tested:** G10, 1983–2012 (MSSS); robust out-of-sample.
- **Evidence:** Strong Sharpe (~0.6–0.8) historically; statistically significant.
- **Decay:** Momentum premia weakened post-publication and especially across 2009–2013; "momentum crashes" (Daniel & Moskowitz 2016) hit currencies in 2009 and 2013. Still positive long-run but smaller.
- **Trade frequency:** ~12 trades/yr per pair (monthly rebalance).
- **Retail difficulty:** Low (simple); needs long clean history.
- **Compatibility:** D1 from 2010 gives ~16y — adequate. But only 4 USD-hub pairs; a real portfolio needs more.
- **Additional data:** More pairs (ideally 10–20) for diversification; daily or monthly closes.
- **Failure conditions:** 2009/2013 momentum crashes; central-bank-driven regime shifts; prolonged range markets.
- **Overfitting risk:** LOW (parameter is standard 12/1).
- **Recommended priority:** HIGH — clean, simple, well-documented, and structurally different from the rejected currency-strength family.

### 2. Carry
- **Source:** Fama (1984) uncovered interest parity; Brunnermeier, Nagel & Pedersen (2008), *Carry Trades and Currency Crashes*, NBER w14473 / JFE; Lustig, Roussanov & Verdelhan (2011) dollar factor.
- **Rationale:** High-yield currencies tend to outperform low-yield (excess return compensates crash risk / funding-liquidity risk).
- **Timeframe:** Weekly–monthly roll.
- **Data:** **Interest-rate differential** (short-term rate spread) + spot/forward. **Markets:** broad, 1980s–present.
- **Evidence:** Large historical Sharpe (~0.5–1.0) but highly negatively skewed.
- **Decay:** 2008–2009 carry crash wiped ~multi-year gains; premia lower post-2008; still pays small positive mean but with tail risk.
- **Trade frequency:** Low (~12–52/yr).
- **Retail difficulty:** Medium (needs rate data).
- **Compatibility:** **NOT available in MT5 price data** — requires interest-rate series.
- **Additional data:** Short-term sovereign/deposit rates per currency (or swap-implied yields).
- **Failure conditions:** Risk-off unwinds, GFC-style crashes, rate-correlation breakdowns.
- **Overfitting risk:** LOW.
- **Recommended priority:** MEDIUM-HIGH (strong literature) but **blocked by data** until rates are sourced.

### 3. Carry + trend filter
- **Source:** Brunnermeier-Nagel-Pedersen (2008); later practitioners add time-series trend filter to cut crash risk (e.g. only hold carry when trend intact).
- **Rationale:** Trend filter skips carry exposure during deleveraging episodes, reducing left tail.
- **Timeframe:** Weekly carry + daily/monthly trend gate.
- **Data:** Rates + price (trend). **Markets:** broad.
- **Evidence:** Reduces crash exposure; modest Sharpe improvement over raw carry.
- **Decay:** Inherits carry decay + filter whipsaw in choppy regimes.
- **Trade frequency:** Low.
- **Retail difficulty:** Medium.
- **Compatibility:** Blocked by rate data.
- **Additional data:** Rates + a trend signal.
- **Failure conditions:** Filter false-positives in volatile trends; carry crash during filter "on".
- **Overfitting risk:** MEDIUM (filter parameter).
- **Recommended priority:** MEDIUM-HIGH (pending rates).

### 4. Cross-sectional momentum
- **Source:** Asness-Moskowitz-Pedersen (2013); Burnside, Eichenbaum, Kleshchelski & Rebelo (2011), *Do Peso Problems Explain Carry Trade Returns?*, RFS.
- **Rationale:** Long strongest / short weakest currencies in a cross-section (relative ranking, not absolute).
- **Timeframe:** Monthly.
- **Data:** ≥8–10 pairs for a meaningful cross-section. **Markets:** G10.
- **Evidence:** Significant cross-sectional spread; distinct from time-series momentum.
- **Decay:** Similar to #1 post-2010 softening.
- **Trade frequency:** ~12/yr.
- **Retail difficulty:** Low–Medium.
- **Compatibility:** Current 4-pair universe is **too small** for a robust cross-section (this was a core limitation in the rejected currency-strength study).
- **Additional data:** ≥10 pairs (add EURGBP, EURJPY, AUDJPY, GBPJPY, CAD, CHF, NZD…).
- **Failure conditions:** Correlated unwinds; small-cross-section noise.
- **Overfitting risk:** LOW-MEDIUM.
- **Recommended priority:** HIGH — but **requires expanding the pair universe** before preregistration.

### 5. Value / PPP
- **Source:** Asness-Moskowitz-Pedersen (2013); Rogoff & Husted (PPP); Engel & West (2005) exchange-rate disconnect.
- **Rationale:** Buy undervalued (cheap vs PPP) / sell overvalued currencies; mean-reversion to fair value.
- **Timeframe:** Quarterly–annual (PPP adjusts slowly).
- **Data:** **PPP / CPI / real-rate macro series**. **Markets:** broad.
- **Evidence:** Weak and slow; PPP half-life ~3–5 years; poor short-horizon timing.
- **Decay:** Long-known, no clear "decay" but consistently weak standalone.
- **Trade frequency:** Very low (4–12/yr).
- **Retail difficulty:** Medium (macro data).
- **Compatibility:** Macro data NOT in MT5 price feed.
- **Additional data:** OECD/World-Bank PPP, CPI per currency.
- **Failure conditions:** Extended misalignment (EUR/USD 2001–2008); discount-rate shifts.
- **Overfitting risk:** LOW.
- **Recommended priority:** MEDIUM (weak standalone; better as a factor in #10).

### 6. Volatility-managed momentum
- **Source:** Moreira & Muir (2017), *Volatility-Managed Portfolios*, Journal of Finance (documents effect for equities, value, momentum, **and the currency carry trade**).
- **Rationale:** Scale exposure inversely to recent realized volatility → higher Sharpe, smaller drawdown, large alpha vs static.
- **Timeframe:** Monthly momentum signal × daily/weekly vol-scaling.
- **Data:** Returns + realized vol (H1 fine). **Markets:** tested across asset classes incl. FX carry.
- **Evidence:** Robust Sharpe improvement where applied; not yet a standalone FX-momentum paper but method transfers.
- **Decay:** Vol-scaling is mechanical, less prone to publication decay than the alpha itself.
- **Trade frequency:** Same as underlying momentum (~12/yr) with intra-month scaling.
- **Retail difficulty:** Low–Medium.
- **Compatibility:** H1 data supports vol estimate; 4 pairs enough to test, better with more.
- **Additional data:** None beyond price (vol computed).
- **Failure conditions:** Vol estimates lag in regime shifts; vol-of-vol spikes.
- **Overfitting risk:** LOW-MEDIUM (scaling window).
- **Recommended priority:** HIGH — a low-cost enhancement layered on #1/#4, fully supportable on current data.

### 7. Defensive risk-off filter
- **Source:** Ranaldo & Söderlind (2010), *Safe Haven Currencies*, Review of Finance 14(3):385–407; IMF WP/13/08; Hossfeld & MacDonald (2014).
- **Rationale:** Reduce/flatten risk-bearing FX exposure during risk-off episodes (VIX spikes, funding-liquidity stress) using a defensive overlay.
- **Timeframe:** Daily/weekly state flag.
- **Data:** A risk proxy (VIX, or cross-asset vol). **Markets:** applied to any FX book.
- **Evidence:** Safe-haven JPY/CHF appreciate in risk-off; an overlay cuts tail risk.
- **Decay:** Structural (funding-currency role) — persistent.
- **Trade frequency:** Overlay (0–few extra trades).
- **Retail difficulty:** Medium (needs a risk proxy).
- **Compatibility:** VIX is external; can be fetched, not in MT5 feed.
- **Additional data:** VIX or a proxy volatility series.
- **Failure conditions:** False risk-off signals; safe-haven regime changes.
- **Overfitting risk:** MEDIUM (threshold).
- **Recommended priority:** MEDIUM — best used as a risk overlay on #1/#2/#4, not standalone.

### 8. Multi-factor carry / value / momentum
- **Source:** Asness-Moskowitz-Pedersen (2013) (value+momentum everywhere); Lustig-Roussanov-Verdelhan dollar factor; Koijen et al. *Betting Against Correlation*.
- **Rationale:** Combine carry + value + momentum — negatively correlated premia diversify; stronger Sharpe, smaller drawdown than any single factor.
- **Timeframe:** Monthly rebalance of z-scored factor portfolio.
- **Data:** Rates + PPP/macro + price. **Markets:** broad G10+.
- **Evidence:** Strongest risk-adjusted of the family; combination premia documented across asset classes.
- **Decay:** Each factor decayed somewhat; combination more robust but smaller than original.
- **Trade frequency:** ~12/yr per factor.
- **Retail difficulty:** High (multi-source data merge).
- **Compatibility:** Needs rates + macro — not in current feed.
- **Additional data:** Rates, PPP/CPI, broad pairs.
- **Failure conditions:** Simultaneous factor drawdowns (rare but possible); data-merge errors.
- **Overfitting risk:** MEDIUM-HIGH (weights, z-scores).
- **Recommended priority:** MEDIUM — strongest theoretically but furthest from current data.

### 9. Seasonality (month / quarter-end)
- **Source:** Mostly practitioner (month-end/quarter-end rebalancing flows); academic: "January effect in FX" (hal-02314156, AMU). Thin peer-reviewed backing.
- **Rationale:** Recurring calendar flows (pension/portfolio rebalancing at month/quarter-end) create small systematic tilts.
- **Timeframe:** Intra-month / turn-of-month windows.
- **Data:** Price only. **Markets:** major.
- **Evidence:** Anecdotal/small; easily overpowered by macro & risk sentiment.
- **Decay:** Unstable; patterns shift as flows evolve.
- **Trade frequency:** ~12–48/yr (short windows).
- **Retail difficulty:** Low.
- **Compatibility:** Works on current data but signal is weak.
- **Additional data:** None.
- **Failure conditions:** Dominant macro catalysts override calendar; regime changes.
- **Overfitting risk:** HIGH (many calendar windows to mine).
- **Recommended priority:** LOW-MEDIUM — **credible evidence is thin**; include only as a minor overlay, not a core candidate.

### 10. Carry + volatility-managed momentum
- **Source:** Synthesis of #2 + #6 (Brunnermeier-Nagel-Pedersen 2008; Moreira-Muir 2017).
- **Rationale:** Carry book with vol-scaled momentum overlay — captures carry premium while damping both carry crashes and momentum volatility.
- **Timeframe:** Monthly carry + vol-scaled momentum gate.
- **Data:** Rates + price + vol. **Markets:** broad.
- **Evidence:** Combines two documented effects; mechanical vol-scaling is robust.
- **Decay:** Inherits carry decay; vol-scaling mitigates.
- **Trade frequency:** Low–Medium.
- **Retail difficulty:** Medium-High.
- **Compatibility:** Blocked by rate data.
- **Additional data:** Rates.
- **Failure conditions:** Carry crash during "on" state; vol-lag in fast regimes.
- **Overfitting risk:** MEDIUM.
- **Recommended priority:** MEDIUM-HIGH (pending rates).

---

## Recommended 2–3 candidates for preregistration

1. **#1 Slow time-series momentum (12M/1M) — PRIMARY.** Cleanest, lowest-overfitting, well-documented, structurally distinct from the rejected family, and fully supportable on the existing D1 history (2010→2026). Caveat: expand the pair universe beyond 4 USD-hub pairs for diversification; the current 4-pair limit was a key weakness.
2. **#6 Volatility-managed momentum — ENHANCEMENT / co-primary.** Pure price-data method (H1 vol estimate), no extra feeds; layer on #1 to improve Sharpe/drawdown. Highest data-compatibility of all candidates.
3. **#4 Cross-sectional momentum — SECONDARY (conditional).** Promising and distinct, but requires expanding to ≥10 pairs first; preregister only after the universe is widened (otherwise it repeats the currency-strength limitation).

**Not yet actionable (data-blocked):** #2, #3, #5, #8, #10 all require **interest-rate and/or PPP/macro series** not present in the MT5 price feed. Recommend sourcing short-term rate differentials + CPI/PPP before preregistering them.

**Explicitly deprioritized:** #9 seasonality — credible academic evidence is thin and overfitting risk is high; keep only as a possible minor overlay, not a core candidate.

---

## Next step (not yet executed)
Do NOT backtest. Next milestone would be: (a) widen the pair universe (add EURGBP, EURJPY, AUDJPY, GBPJPY, USDCHF, USDCAD, NZDUSD, etc.) and (b) optionally source interest-rate / VIX series, then preregister #1 (and #6 overlay) with frozen parameters, folds, controls, and acceptance gates before any evaluation.
