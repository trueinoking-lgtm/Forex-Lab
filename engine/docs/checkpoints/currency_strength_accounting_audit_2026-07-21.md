# Currency-Strength Accounting and Scope Audit

**Date:** 2026-07-21
**Classification:** 1. REJECT STRATEGY FAMILY
**Frozen configuration hash:** `f9d222776a2c91049d2633d08d25a391ba00f774b065330d042d164382503e3f`

Research-only reconciliation of accounting and result scope. No parameter, gate, signal construction, or frozen candidate was changed. Audit mode loads only `{"atr_stop": 2.0, "filter": "continuation", "holding": 24, "lookback": 24, "method": "equal_weight", "target_r": 1.5}` and does not enumerate or reselect the 405 configurations.

## Findings

The return below -100% was the fixed-notional additive sum (`sum(net_pnl_usd) / 10000`) mislabeled as portfolio return. It remains available only as `arithmetic_return_sum`. The drawdown above 100% came from an unfloored `10000 + cumulative PnL` curve. The corrected shared-equity ledger applies `max(0, equity + net_pnl)` to trades ordered by exit timestamp, declares bankruptcy at zero, and rejects every later trade from portfolio metrics.

The sole gate-bearing scope is `chronological_test` (2025-01-01 through 2026-07-17 23:59:59). DEV, VALIDATION, TEST, aggregate TEST, and full-history diagnostics are separate records with disjoint fold trade identifiers. Persisted selection inputs and a hidden-TEST replay prove selection depends only on DEV and VALIDATION. The exact concentration rule is `max(currency_frac) <= 0.5 AND USD <= 0.5`; the 0.50 boundary is inclusive.

## Before / after

| Metric | Original | Corrected | Reason |
|---|---:|---:|---|
| Test trades | 6369 | 1908 | Original aggregate included DEV and VALIDATION; corrected value is TEST-only |
| PF | 0.8432374770861003 | 0.8134266618588784 | TEST-only accepted shared-equity ledger |
| Expectancy (USD/trade) | -4.426488481605748 | -5.242088505578104 | TEST-only accepted shared-equity ledger |
| Arithmetic return sum | -2.8192305139347007 | -2.7887141825018618 | Fixed-$100 additive diagnostic retained under its correct name |
| Portfolio return | -2.8192305139347007 | -1.0 | Floored shared portfolio equity |
| Ending equity | -18192.30513934701 | 0.0 | Original curve was unfloored; corrected curve floors at zero |
| Max drawdown | 2.580106433575472 | 1.0 | Floored curve bounds drawdown to [0,1] |
| Bankrupt | not reported | True | Explicit shared-equity bankruptcy state |
| Robustness | 0.0 | 0.0 | TEST-only pair outcomes |
| Score | 0.0 | 0.0 | Uses portfolio return; arithmetic diagnostic cannot drive gates |
| Classification | 1. REJECT STRATEGY FAMILY | 1. REJECT STRATEGY FAMILY | Corrected chronological gates do not all pass |

## Historical diagnostics

All periods are `full_historical_diagnostic` and never enter eligibility. All four immutable H1 inputs begin 2010-01-04, so 2010-2014 is evaluated rather than marked unavailable.

- 2010_2014: trades=2554, PF=0.851981, arithmetic=-6.644193, portfolio=-1.000000, max DD=1.000000, bankrupt=True
- 2015_2019: trades=2408, PF=0.848361, arithmetic=-7.800239, portfolio=-1.000000, max DD=1.000000, bankrupt=True
- 2020_2022: trades=2317, PF=0.842184, arithmetic=-3.475821, portfolio=-1.000000, max DD=1.000000, bankrupt=True
- 2023_2026: trades=1557, PF=0.778351, arithmetic=-6.002818, portfolio=-1.000000, max DD=1.000000, bankrupt=True

Rolling three-year and five-year windows plus high/low-volatility regimes are in `currency_strength_period_stability_corrected.json`.

## Contributions

TEST pair gross-profit fractions: `{"AUDUSD": 0.2870064923639643, "EURUSD": 0.19634278268389518, "GBPUSD": 0.16762636156678723, "USDJPY": 0.3490243633853533}`. TEST currency gross-profit fractions: `{"AUD": 0.14350324618198215, "EUR": 0.09817139134194759, "GBP": 0.08381318078339361, "JPY": 0.17451218169267665, "USD": 0.5}`.

The final classification remains **1. REJECT STRATEGY FAMILY**. Audit artifacts use accounting v2 and are runtime-generated under the ignored `engine/results/` directory.
