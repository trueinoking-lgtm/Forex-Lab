# FX Carry Research — Phase 0 Data Readiness Report

**Date:** 2026-07-24
**Status:** RATE-DIFFERENTIAL PROXY READY — EXECUTABLE CARRY DATA MISSING
**Scope:** Research and data-readiness only. `paper_only=true`, `ALLOW_LIVE_ORDERS=false`. No strategy implementation, no trading signals, no backtests, no orders.

---

## 1. Carry Concept Definition

FX carry is the return earned (or cost incurred) from holding a position in a currency pair where the two legs have different overnight funding rates. In its simplest form, a long USD/JPY position earns the USD funding rate (e.g., EFFR) and pays the JPY funding rate (e.g., TONA), netting the differential.

Five distinct concepts must not be conflated:

1. **Policy-rate differential** — the difference between two central bank policy rates (e.g., the Fed Funds rate vs. the BOJ policy rate). This is a coarse indicator of the interest-rate environment but is not a funding cost.
2. **Overnight benchmark-rate differential** — the difference between two overnight transaction benchmarks (e.g., EFFR vs. TONA). This is the closest approximation to actual funding costs available from public data.
3. **Theoretical FX carry** — the carry implied by the overnight benchmark differential applied over a holding period, ignoring transaction costs, margin, slippage, and roll conventions.
4. **Forward-implied carry** — the carry implied by the forward points (or FX futures basis), which embed the interest-rate differential plus market expectations and risk premiums.
5. **Actual broker swap/rollover credited or charged** — what a real FX trader pays or earns on a broker-managed overnight roll. This includes broker markups, account-specific financing terms, triple-roll conventions, holiday calendars, and counterparty-specific terms.

This phase addresses categories 1-4. Category 5 (actual broker swaps) is not available from official public sources and remains the principal unresolved data gap.

---

## 2. Why Policy Rates Alone Are Insufficient

Central bank policy rates (e.g., Fed Funds Rate, ECB Deposit Facility Rate, Bank Rate, BOJ Policy Rate, RBA Cash Rate) are set at discrete committee meetings and represent the top of the central bank's corridor or the policy stance. They are NOT the rate at which market participants fund overnight positions.

The actual funding cost is the overnight transaction benchmark — unsecured in most major currency zones (EFFR, €STR, SONIA, TONA, AONIA) or secured in the case of SOFR. Policy rates are useful as:

- A long-run comparison anchor
- A diagnostic indicator of the monetary policy regime
- A way to identify structural breaks and methodology changes

But policy rates must never silently substitute for a transaction benchmark in a daily carry panel. The source registry includes policy rates only as fallback/diagnostic entries, explicitly labelled as unsuitable for daily carry input.

---

## 3. Official Source Assessment by Currency

### USD
- **EFFR (Federal Funds Effective Rate)** — New York Fed — FEDFUNDS series. Public domain. No API key required. Published roughly 09:00 ET. FRED API (dailyhistorical). Available since 1954. No historical revisions. **PASS** all data-quality gates.
- **SOFR (Secured Overnight Financing Rate)** — New York Fed — SOFR series. Public domain. Available since 2013-04-03. Published ~08:00 ET next business day. FRED API. No material methodology changes. **PASS** all data-quality gates. Note: secured; not interchangeable with unsecured EFFR.

### EUR
- **€STR** — ECB — ESTR series. Available from official start 2019-10-03. Published 09:00 CET. ECB statistical data warehouse. Public (non-commercial use with attribution). **PASS** for post-2019 period. Pre-2019 EUR carry must use EONIA.
- **EONIA** — ECB/EMMI — EONIA series. Available 1999-01-04 to 2019-09-30 (archived through 2022-01-03 under €STR-plus-spread methodology). Published 09:00 CET. ECB statistical data warehouse. Public (non-commercial with attribution). **PASS** for pre-2019 period. Methodology break at 2019-10-03 when €STR replaced it.
- **ECB Policy Rates** — Fallback diagnostic only. Weekly. Not suitable for daily carry input. **FLAGGED** as diagnostic fallback.

### GBP
- **SONIA (reformed April 2018)** — Bank of England — SONIA series. Published 09:00 GMT next business day. Transaction-based method. Available from 1997-01-06 (original); reformed methodology from 2018-04-02. Public sector information. **PASS** for carry calculations. Note methodology break at April 2018 reform.
- **Bank Rate** — Fallback diagnostic only. Weekly. Not a daily funding rate. **FLAGGED** as diagnostic fallback.

### JPY
- **TONA (Uncollateralized Overnight Call Rate)** — Bank of Japan — TONA series. Published next business day (BOJ time). Available from 1979-01. Public, no authentication required. **PASS** with regime-awareness: dynamics differ materially pre-2016 (positive corridor), 2016-2024 (NIRP/YCC), and post-2024 (exit from YCC).
- **BOJ Policy Rate** — Fallback diagnostic only. Set at discrete meetings. **FLAGGED** as diagnostic fallback.

### AUD
- **AONIA / BBSW** — Reserve Bank of Australia. AONIA as RBA-calculated series from circa 2020 (RBA took over from AFMA). BBSW history from ~1990s. Transaction-based. RBA Statistical Table F1 provides cash rate (weekly); AONIA daily values from RBA website. **PASS** with noted limitations: BBSW historical data has narrower panel than AONIA; republication rules apply (RBA copyright notice required).
- **RBA Cash Rate** — Fallback diagnostic only. Weekly. Not a daily observable. **FLAGGED** as diagnostic fallback.

### Cross-Check
- **BIS Central Bank Policy Rate Dataset** — BIS, https://www.bis.org/statistics/centralbank_rates.htm. Useful for long-run comparison and methodology-break identification. Does NOT replace overnight transaction benchmarks. **PASS** as cross-check reference only.

---

## 4. Coverage Table from 2010 Onward

| Currency | Overnight Benchmark | 2010 Onward? | Notes |
|----------|-------------------|-------------|-------|
| USD | EFFR | ✅ Yes | Available since 1954; no gaps |
| USD | SOFR | ⚠️ Partial | Available from 2013-04-03 only; no secured proxy pre-2013 |
| EUR | EONIA (pre-2019) | ✅ Yes | Available 2010-2019; methodologically distinct from €STR |
| EUR | €STR (post-2019) | ✅ Yes | Available from 2019-10-03 onward |
| GBP | SONIA (reformed) | ✅ Yes | Reformed April 2018; pre-reform SONIA available but methodologically different |
| JPY | TONA | ✅ Yes | Available since 1979 with regime breaks |
| AUD | AONIA / BBSW | ✅ Yes | BBSW historical from ~1990s; AONIA full series from ~2020 |

---

## 5. Methodology-Break Table

| Currency | Benchmark | Break Date | Description | Impact on Carry Calculations |
|----------|-----------|-----------|-------------|------------------------------|
| EUR | EONIA → €STR | 2019-10-03 | Quote-based bank panel → transaction-based panel | Carry calculations across this boundary are not directly comparable; regime must be labelled explicitly |
| GBP | SONIA reformed | 2018-04-02 | Quote-driven average → transaction-based | Pre-April 2018 and post-April 2018 SONIA are not directly comparable at the boundary |
| JPY | NIRP/YCC regime | 2016-01-29 (NIRP) / 2016-02-16 (YCC) | Overnight rate pushed negative; YCC capped the yield curve | Carry calculations 2016-2024 are structurally different from pre-2016 and post-2024 |
| JPY | YCC exit | 2024 | BOJ began normalising, raising the short end | Post-2024 TONA dynamics differ from NIRP/YCC period |
| AUD | AONIA takeover | ~2020 | RBA took over AONIA calculation from AFMA; broader panel | Continuity consideration; both BBSW and AONIA are transaction-based |
| USD | EFFR publication | ~2017 | NY Fed shifted publication from ~18:00 ET to ~09:00 ET | Affects usability windows but not the underlying rate |

---

## 6. Publication and Revision Policy

| Benchmark | Publication Lag | Revision Policy | Historical Revisions |
|-----------|----------------|----------------|---------------------|
| EFFR | ~12-18h after value-date close | No historical revisions | None |
| SOFR | Overnight (T+1 morning) | No material changes since inception | None |
| €STR | Overnight (09:00 CET next business day) | No revisions since official start | None |
| EONIA | Overnight (09:00 CET next business day) | Archived as static historical series | None |
| SONIA | Overnight (09:00 GMT next business day) | No revisions to historical values | None |
| TONA | Overnight (next business day BOJ time) | No historical revisions | None |
| AONIA / BBSW | Overnight (next business day AEST) | No revisions to reported values | None |

---

## 7. Holiday/Calendar Alignment Plan

Each market has its own holiday calendar:

- **USD** — US federal holidays (NYSE schedule)
- **EUR** — TARGET holidays (EU settlement system)
- **GBP** — UK bank holidays
- **JPY** — Japanese bank holidays
- **AUD** — Australian public holidays

For the daily panel, missing-value policy for each benchmark is **no interpolation**. If a benchmark is not published on a holiday, that date has no value for that currency. The pair differential schema will reflect data_availability at the currency level, so a missing AUD value on a non-observed Australian holiday does not affect USD or EUR carry calculations.

Calendar alignment is important for the lookahead safety rule: a rate observation published on the next business day must not be assigned to a trading decision made on the prior trading day if the publication has not yet occurred.

---

## 8. Benchmark Transition Handling

Regime breaks are handled by the `methodology_regime` field in the canonical daily schema. The schema records the applicable regime for each observation, allowing researchers to:

- Filter by regime (e.g., `methodology_regime_base == 'SONIA_reformed'` for post-April-2018 GBP)
- Exclude observations from one regime when comparing across a transition boundary
- Document which regime was active at the time of any research conclusion

For EUR, the EONIA→€STR transition on 2019-10-03 is handled by using EONIA for dates 2010-01-01 to 2019-10-02 and €STR for dates 2019-10-03 onward. The EONIA series is preserved as the correct pre-transition benchmark.

For SONIA, pre-April 2018 observations use `methodology_regime_base = "SONIA_pre_reform"` and post-April 2018 use `"SONIA_reformed"`. Both series are labeled SONIA but are not directly comparable at the boundary.

For JPY, TONA observations are tagged with the applicable regime: `"pre_NIRP"`, `"NIRP_YCC"`, or `"post_YCC_exit"`. The BOJ operating framework changed materially in each period.

---

## 9. Forward-Points and Broker-Swap Availability Assessment

### Official / Exchange-Based FX Futures Basis
- **CME FX Futures** (e.g., 6E for EUR/USD, 6B for GBP/USD, 6J for USD/JPY, 6A for AUD/USD) provide forward-implied rates and basis to the spot. These are exchange-traded and publicly available with historical data. Suitable for forward-implied carry calculations but do not account for broker-specific markups or account-level financing.

### Historical Forward Points
- **Delivery forward points** from official forex dealer quotation archives (e.g., Reuters, Bloomberg historical snapshots) are the standard market input. However, these are typically proprietary and require licensed data access (e.g., Refinitiv/Reuters, Bloomberg Terminal). Not available from free or public sources.

### Broker-Specific Overnight Swap History
- **Not available from official public sources.** Broker swap/rollover rates are account-specific, embed broker markups and financing costs, and are not published in any open dataset. Triple-roll conventions (Monday/Tuesday/Friday rolls) and holiday calendars are also broker-specific. **Cannot be sourced from official or exchange-based data.**

### Assessment
- **Forward-implied carry** (from CME FX futures or delivery forward points, where available) is constructable for academic signal research.
- **Actual broker swap/rollover data** (the real cost of carry for a trader) is not available from official public sources. This includes markups, account-specific financing terms, triple-roll conventions, and broker holiday calendars.
- The verdict is: **rate-differential proxy is ready; executable carry data (category 5: actual broker swap/rollover) is missing.**

---

## 10. Legal/Licensing Assessment

| Source | License / Terms | Restrictions |
|--------|----------------|--------------|
| NY Fed (EFFR, SOFR) | Public domain | None |
| ECB (€STR, EONIA, policy rates) | ECB statistical terms — non-commercial use with attribution | No commercial redistribution without separate agreement |
| Bank of England (SONIA, Bank Rate) | Public sector information — free with attribution | Attribution required |
| Bank of Japan (TONA, policy rate) | Public — BOJ statistical data | None |
| RBA (AONIA, BBSW, cash rate) | Public sector information — free with attribution and copyright notice | Republication requires RBA copyright notice; commercial use may require separate agreement |
| BIS (policy rates cross-check) | BIS data terms — generally permitted for research with attribution | None for non-commercial research |
| CME FX Futures | Exchange data — subscription required for historical access | Licensed; not part of free public data sources |

**Licensing verdict:** All primary overnight benchmarks have licenses that permit academic research storage and use with attribution. The only potential restriction is the BIS data terms (which allow research use) and the RBA republication rule (attribution + copyright notice). No material licensing gaps exist for the primary benchmarks. CME FX futures data requires a subscription and is not included in the free panel.

---

## 11. Proposed Canonical Daily Schema

```
observation_date          date     — date of the observation (value date)
currency                  string   — USD, EUR, GBP, JPY, AUD
benchmark_name            string   — e.g., EFFR, €STR, SONIA, TONA, AONIA
benchmark_rate_percent    number   — rate in percent (e.g., 5.25 = 5.25%)
benchmark_type            string   — overnight_unsecured, overnight_secured, policy_rate_weekly
secured_unsecured         string   — unsecured, secured_triparty_repo, n/a_policy_rate
value_date                date     — the value date (T-1 for most benchmarks)
publication_timestamp_utc timestamp — when the rate was published in UTC
source_revision_status    string   — current, archived, methodology_changed
methodology_regime        string   — e.g., "EFFR", "SONIA_reformed", "pre_NIRP", "post_YCC_exit"
source_series_id          string   — exact series identifier (e.g., FEDFUNDS, ESTR, SONIA, TONA)
source_file_sha256        string   — SHA-256 of the source file used to acquire this rate
acquisition_timestamp_utc timestamp — when we acquired and stored this rate
```

### Pair Differential Schema

```
observation_date        date     — date of the observation
pair                    string   — e.g., EURUSD, GBPUSD, USDJPY, AUDUSD
base_currency_rate      number   — rate of the base currency (left side of pair)
quote_currency_rate     number   — rate of the quote currency (right side of pair)
raw_rate_differential   number   — base_rate - quote_rate (in percent)
data_available_timestamp_utc timestamp — when both rates became available
methodology_regime_base string   — regime tag for the base currency benchmark
methodology_regime_quote string  — regime tag for the quote currency benchmark
```

---

## 12. Data-Quality Gates

A source passes the data-quality gates only if ALL of the following are true:

1. **Official or institutionally authoritative** — the source is the designated publisher (e.g., NY Fed for EFFR/SOFR, ECB for €STR/EONIA, BoE for SONIA, BOJ for TONA, RBA for AONIA).
2. **Machine-readable or reproducibly extractable** — the data is available as CSV or JSON from an official API or data warehouse.
3. **Methodology documented** — the methodology (secured/unsecured, transaction-based vs quote-based, panel composition) is publicly described by the publishing institution.
4. **Publication timing documented** — the publication time, lag, and value-date semantics are publicly documented.
5. **Revision policy documented** — the source confirms whether historical values are revised or stable.
6. **Coverage sufficient for intended folds** — the source covers the entire 2010-onward window for its currency (with appropriate regime labels for breaks).
7. **No unexplained timestamp ambiguity** — the publication timestamp and value-date semantics are unambiguous and documented.
8. **Licensing permits storage and use** — the license allows academic research storage and use with attribution.

All five currency benchmarks identified in this report pass these gates. The BIS cross-check dataset also passes for cross-reference use, with the caveat that it is not an overnight transaction benchmark.

---

## 13. Feasibility Verdict

### RATE-DIFFERENTIAL PROXY READY — EXECUTABLE CARRY DATA MISSING

**Reasoning:**

The rate-differential proxy (categories 1-4) is constructable for academic signal research. All five currencies have official institutional sources for overnight transaction benchmarks with machine-readable format, documented methodology, documented publication timing, documented revision policy, sufficient coverage for 2010 onward, and licenses permitting academic storage and use. The methodology breaks (EONIA→€STR, SONIA reform, JPY regime changes, AUD panel transition) are all documented and taggable via the `methodology_regime` field.

However, actual broker swap/rollover data (category 5 — the real cost of carry for an FX trader) is not available from official public sources. Broker-specific markups, account-specific financing, triple-roll conventions, and broker holiday calendars are not documented in any open dataset. Forward points from CME FX futures provide an exchange-based proxy for forward-implied carry, but do not account for broker-specific financing terms.

Therefore: the rate-differential proxy is ready, but executable carry data (the actual funding cost a trader pays) is missing.

**Classification:** RATE-DIFFERENTIAL PROXY READY — EXECUTABLE CARRY DATA MISSING

---

## Source Registry Summary

Total sources catalogued: **11 primary benchmarks + 1 cross-check reference + 5 policy-rate diagnostic fallbacks = 12 records in source registry**.

Primary overnight transaction benchmarks (suitable for daily carry panel):
1. USD — EFFR (FEDFUNDS)
2. USD — SOFR
3. EUR — €STR (ESTR)
4. EUR — EONIA (historical, 2010-2019)
5. GBP — SONIA (reformed April 2018)
6. JPY — TONA
7. AUD — AONIA

Policy-rate fallback/diagnostic (NOT suitable as daily carry input):
8. EUR — ECB Deposit Facility Rate / MRO / LFR
9. GBP — Bank Rate
10. JPY — BOJ Policy Rate (overnight call facility rate)
11. AUD — RBA Cash Rate

Cross-check reference:
12. BIS Central Bank Policy Rate Dataset

---

## Lookahead Safety Reminder

A rate observation may only become usable after its documented publication time. Do not assign a rate to an earlier trading decision merely because its value date belongs to the previous business day. Publication lag is explicitly documented for every benchmark in the source registry. The `publication_timestamp_utc` field in the canonical daily schema enforces this constraint programmatically.