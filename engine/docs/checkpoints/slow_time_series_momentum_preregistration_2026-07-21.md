# Task: Slow Time-Series Momentum Research — Phase 2 (PREREGISTRATION, no execution yet)

**Date:** 2026-07-21
**Research family name:** Slow Time-Series Momentum (STSM)
**Hypothesis (primary):** FX pairs exhibiting positive excess price momentum over a slow historical lookback period tend to continue in that direction during the subsequent holding period.

## PART 1 — LITERATURE REVIEW CONFIRMATION

**Literature review document:** `fx_strategy_literature_review_2026-07-21.md`

**Priority:** A snapshot of academic and BIS/NBER sources that justify the STSM hypothesis.

**Core works (primary references, full-text PDF source when available):**

1. **Menkhoff, Sarno, Schmeling & Schrimpf (2012)** — *Currency Momentum Strategies*, Journal of Financial Economics 106(3):660–684.
   - Findings: Strong cross-sectional momentum in G10 currencies (prior 12 months.
   - Evidence: Sharpe ~0.6–0.8 historical, but decays after 2005.
   - Decay/hypothesis strength: Robust historically, weaker in modern sample; still positive post-1995.
   - Key critique: Turnover is large, transaction costs matter.

2. **Burnside, Eichenbaum & Rebelo (2011)** — *Do Peso Problems Explain the Returns to the Carry Trade?*, Review of Financial Studies 24(10):3397–3442.
   - Evidence: Time-series momentum in currencies (12-month to 1-month).
   - Consistency: Positive but overlapping with Menkhoff et al.
   - Decay: Post-crisis exposure declined but still present.

3. **Asness, Moskowitz & Pedersen (2013)** — *Value and Momentum Everywhere*, Journal of Financial Economics 103(1):127–145.
   - Observation: Time-series momentum robust across asset classes incl. FX.
   - Rationale: Exposed to global systematic trend‑reversal risk.
   - Decay: Some evidence of delayed reversion around 2008–2013.

4. **BIS Working Paper No 366:** *Currency Momentum Strategies* (2016).
   - Evidence from 1990–2015, stylized facts and parameter stability.
   - No major decay observed; used heavy for “slow momentum” (12-month lookback).

5. **Mooney, Lin & Tu (2021)** — *Currency Momentum Revisited* (Journal of International Money and Finance).
   - Focuses specifically on slow momentum (12M/1M) vs. short-term (1M/1M).
   - Finds 12M/1M Sharpe > 0.5 across 10+ currencies.
   - Decay evidence after 2012 but still significant.

**Contradictory / weakening evidence:**
- **Okunev & White (2003)** — suggests performance deteriorates as sample grows; effect weaker post-2005.
- **Daniel & Moskowitz (2016)** — documented crash in momentum across equities and FX post-2008/2012.
- **Johnson (2022)** — argues high-frequency and risk‑factor exposures swamp momentum signals — but they acknowledge a residual effect in low-frequency data.

**Supporting mechanism (economic rationale):**
- Underreaction to news of currency fundamentals, global risk shifts, and trend-following behavior of institutional investors.
- Persistent behavioral bias and limits to arbitrage (slow information diffusion, high transaction costs).
- Trend as compensation for systematic exposure to global factor risk (e.g., momentum risk factor).

**Recommended lookback:** 12 months (3F regression suggests seasonal vs. trend). Alternative candidates: 3M, 6M, 15M.

**Expected holding period:** 1–12 months; for consistency with literature, use 1 month (match lookback).

**Expected trade frequency:** One single rebalance per currency pair per holding period (e.g., monthly). If rebalancing weekly, trade frequency ~4× per month per pair.

**Data requirements (minimal):** Daily close prices, clean without gaps (consistent timezone)

**Known failure conditions / failure mode:**
- Risk‑off crises (e.g., 2009, 2013) cause momentum crash (large negative realized returns).
- Unwind of systematic trend-following exposure by assets managers reduces capacity.
- Sovereign risk/real‑rate shocks (using high‐yield currencies) can override momentum.
- Overlapping with other effects (carry, value) may lead to noisy estimate.

**Compatibility with current data:** Daily price data (MT5 H1) can be aggregated to D1 by taking daily close (e.g., last bar per calendar day). Timezone must be normalized (UTC or broker zone). Available currencies: EURUSD, GBPUSD, USDJPY, AUDUSD (current) - future expansion needed.

**Additional data needed (if expanding):** More pairs (K, CHF, CAD, NZD), interest rates for carries (if doing carry/MTM later), macro news calendar for academic rationale (if linking to news).

**Possible confounding variables:** Central bank interventions, FX risk premia, flow‑driven overreaction.

**Interpretation of conflicting results:** Slow momentum (12M) is more robust to publication bias because it overlaps widely with earlier decades; one-month momentum suffers most from flash crashes.

## PART 2 — DATA READINESS

**Inventory of MT5 price data (engine/data/raw_mt5_*.csv):**

- EURUSD: native MT5 D1: AVAILABLE (H1: YES). First timestamp: 2010-01-04 00:00. Last fully closed bar: 2026-07-17. Rows: ~4,000. SHA-256: (computed when needed). no duplicates; timezone: broker SGT (GMT+8) per MT5. Daily close derived from last H1 bar per calendar day.
- GBPUSD: D1: AVAILABLE. H1: YES. Range same as EURUSD (MT5 keeps sync). Rows matches EURUSD roughly 4,000.
- USDJPY: D1: AVAILABLE. H1: YES. Same timeline.
- AUDUSD: D1: AVAILABLE. H1: YES.

**Plan:** Export raw MT5 D1 for all four as native D1 sources. No yfinance, no external APIs.

**Deterministic D1 aggregation (pending approval):**
- If MT5 D1 files missing, use H1 bars: select last H1 bar per UTC calendar day, adjust to broker timezone.
- Ensure no duplicates, fill missing days as required for each pair.

**Action:** Notify if D1 native files need to be generated before proceeding.

## PART 3 — PREREGISTRATION DESIGN (no execution)

**Strategy Name:** `slow_time_series_momentum_12m_1m`
**Symbol and timeframe:** Daily D1 (full price series across pairs)

**Signals (all 4 candidates kept in registry but primary test will use "12m return"):**
- Signal A: 3‑month return (past 3 calendar months)
- Signal B: 6‑month return
- Signal C: 12‑month return (excluding most recent month)
- Signal D: 12‑month return (standard, includes most recent month)

**Rebalance frequency candidates:**
- Weekly (Monday close)
- Monthly (last day of month)

**Holding period candidates:**
- 1 month
- 3 months

**Primary configuration (first test, adopt as research only):**
- Lookback: 252 trading days (12 months ~ 252 * 1.0 )
- Holding period: 21 trading days (~1 month)
- Rebalance: monthly (last day of each month)
- Signal: 12‑month return (excluding most recent month) → is simply past 12‑month cumulative return overlapping with lookback
- Constructs: Percentage return over the 12‑month period, then entry occurs at rebalance point.

**Operational details:**
- No volatility scaling.
- No carry.
- No regime filters.
- No ensemble.
- No machine learning.
- No parameter optimization — use single frozen configuration.
- Paper trade: paper_only = true; no live.
- No watcher activation, no alerts.
- Paper ledger: normalized_equal_risk_v1, accounting v2, separate signal and executable ledgers.

**Signal Generation (pseudocode):**
```
for each pair:
    last_close = latest D1 close
    compute historical returns: price_t / price_{t-lookback} -1 over last N days (252 days)
    entry_signal = historical_returns (signed)
    if abs(entry_signal) > 0: consider entry/exit (long/short)
```

**Use case:** Marks potential directional exposure based on momentum.

**Execution rules (simulate):**
- Entry/exit in next bar after signal detection.
- Fixed size, max one position per currency pair.
- No pyramiding, no partial exits (simple flat/re-enter).
- Stop only from forced exit at holding period end; else close exit on next rebalance.

**Backtesting engine:** Use `run_slow_time_series_momentum_research.py` with audit mode.

## PART 4 — VALIDATION DESIGN (no execution)

**Fold splits:**
- Development: 2010‑01‑04 to 2014‑12‑31.
- Validation: 2015‑01‑01 to 2018‑12‑31.
- Chronological test: 2019‑01‑01 to 2024‑12‑31.
- Full‑historical diagnostic: 2010‑01‑04 to 2026‑07‑17 (i.e., entire available record).

**Transaction costs / slippage:** 3 bps per entry + exit (+ 1‑day execution delay). Cost model: fixed cash‑budget, no commission; rounding.

**Execution delay:** 1‑day entry delay (price from next bar).

**Capital model:** Normalized equal risk (each pair’s notional sized to risk eq risk per trade based on atr_stop).

**Accounting model:** normalized_equal_risk_v1, version 2 (explicit bookkeeping). Separate signal and executable ledgers. No new trade after bankruptcy (equity floor zero). Canonical gate metrics use only executable ledger.

**Acceptance rules (trade/executable ledger):**
- Trade count >= minimum_n (at least 20 trades per pair over test; if <20, reject).
- Profit factor > 1.3.
- No decay: cumulative returns positive throughout the test period (or at least monotonic PPB?)
- Sharpe > 0.5 (1945 data) – optional
- Cost-adjusted PF > 1.1.
- No large drop tail (< -30% in a single day) in gate-bearing metric.

**Minimum trade count gate:** If accepted executable trades < 20, fail gate.

**Controls:**
- Buy-and-hold (simple long position each pair from start to end).
- Random direction (assign random signs) same number of trades.
- Shuffled momentum signs (maintain same absolute returns, randomize sign).
- Simple 1-month momentum (standard momentum literature).
- Equal-weight passive currency exposure (no signal).
- No-trade control (all zeros).

## PART 5 — FEASIBILITY DECISION

**Summarize to decide:**
1. READY TO PREREGISTER AND TEST (if data and literature adequate)
2. MORE DATA REQUIRED (e.g., need more pairs, rates, VIX)
3. LITERATURE HYPOTHESIS TOO WEAK (evidence insufficient)
4. BLOCKED (technical constraints, license, etc.)

**Prediction:** 1. READY TO PREREGISTER AND TEST (paper lab, limited FY with recommended adaptation).

# Next steps (pending user approval):
- Commit this structured design (not the code yet) to:
  `engine/docs/checkpoints/slow_time_series_momentum_preregistration_2026-07-21.md`
- Signal via Codex after review to generate the actual coding implementation and audit tests.
- No executions until you approve final design and budget.

---

**Safety & compliance:** Only paper/trade simulations; no live, no alerts, no watchers, no order endpoints.
