> **SUPERSEDED — accounting only (2026-07-20).** Preserve all original metrics and classification below as historical record. PF, expectancy, gross PnL, and concentration used `legacy_raw_price_units_v1` (version 1). The corrected session-breakout classification is **rejected** (PF 0.708541, return -27.5993%, 857 trades) under `normalized_equal_risk_v1` (version 2); see [Canonical accounting migration](canonical_accounting_migration_2026-07-20.md).

# Multi-Pair H1 Session Breakout — Phase 1 Results

Date: 2026-07-20. Research/paper/demo only. This report does not fabricate data or results: it uses the delivered real H1 MetaTrader 5 demo-history CSVs. Fixed UTC sessions, chronological folds, costs, parameter bounds, gates, and rejection rules remain preregistered and unchanged.

## Inputs and integrity

| pair | raw SHA-256 | raw/evaluated rows | evaluated coverage | gaps | defects |
|---|---|---:|---|---:|---:|
| EURUSD | `80cc20e9de10f929619902d618a32035f45d557751153d16484de46d8d5fcfc1` | 102675/102674 | 2010-01-04 00:00–2026-07-20 18:00 UTC | 894 | 0 |
| GBPUSD | `99a2564ae0040d6c47ec20d1ce84c82a464be44dafac05898ea7e2e53d1fa789` | 102677/102676 | 2010-01-04 00:00–2026-07-20 18:00 UTC | 893 | 0 |
| USDJPY | `3aad2f78b5b06f39ac7804d33845c40e31d2d00073937e2df8eb51512802db60` | 102684/102683 | 2010-01-04 00:00–2026-07-20 18:00 UTC | 892 | 0 |
| AUDUSD | `776a10f7326ba04bf68a7c95011aedeebee693b0c5eb22d2ea22a98332bb94a7` | 102677/102676 | 2010-01-04 00:00–2026-07-20 18:00 UTC | 892 | 0 |

All timestamps are ascending, unique, and UTC; OHLC values are finite/positive and internally valid; volume is nonnegative. Gaps are ordinary FX/weekend/holiday closures; no unexpected non-weekend gap over 72 hours was found. Manifests identify the requested 2010-01-01–2026-07-21 interval, actual 2010-01-04 start, H1 timeframe, MetaTrader5 demo history, sanitized broker/server metadata, and no account number or credential. The possibly incomplete 19:00 candle was excluded deterministically from evaluation without changing any raw CSV. Separate raw and evaluated fingerprints are in every result family.

## Frozen evaluation

The full frozen grid contains 2,916 combinations. Under the preregistered staged allowance, all 27 buffer/minimum/maximum range-filter combinations were screened with the neutral exit; the top three filters were expanded over all 36 frozen stop/target/holding combinations (108 expanded candidates). No DEV+VAL candidate cleared all four selection gates. The best fail-closed diagnostic was buffer 0.10 ATR, no minimum range, maximum 1.5 ATR, opposite-side stop, 1.5R target, and session-close holding.

Folds were whole UTC dates. EURUSD/GBPUSD: DEV through 2019-12-04, VAL 2019-12-05–2023-03-28, TEST from 2023-03-29. USDJPY/AUDUSD: DEV through 2019-12-05, VAL 2019-12-06–2023-03-29, TEST from 2023-03-30. Every TEST ends 2026-07-20 18:00 UTC.

## Chronological test

| scope/pair | trades | wins/losses | PF | return | max DD | robustness | score |
|---|---:|---:|---:|---:|---:|---:|---:|
| EURUSD | 368 | 160/208 | 0.7502 | -9.32% | -10.06% | 0.000 | 17.65 |
| GBPUSD | 368 | 149/219 | 0.5799 | -18.12% | -17.88% | 0.000 | 15.29 |
| USDJPY | 67 | 27/40 | 1.4039 | +2.24% | -1.42% | 1.000 | 55.30 |
| AUDUSD | 54 | 19/35 | 0.6770 | -2.40% | -3.58% | 0.000 | 18.03 |
| **aggregate_cross_pair_test** | **857** | **355/502** | **1.3245** | **-27.60%** | **-27.58%** | **0.000** | **24.60** |

Aggregate PF is recomputed from combined gross profit 12.842505 and gross loss 9.695790, never averaged. Long/short PF is 1.3712/1.2701. Explicit lifecycle, expectancy, exposure, long/short, and open-trade accounting is persisted; there were no open TEST trades.

## Controls, stability, stress, and concentration

Twenty deterministic random controls had median return -145.40% and 90th percentile -137.29%; the candidate beat all runs but not meaningfully because it failed the absolute return, robustness, and score gates. No-trade is 0%; the required alternative control identities are explicitly recorded as diagnostics and are ineligible to rescue the family.

Fixed-period returns were negative in every stratum: 2010–2014 -60.10%, 2015–2019 -44.29%, 2020–2022 -25.79%, and 2023–2026 -28.40%. All fourteen rolling 3-year and all twelve rolling 5-year windows were negative. London summer-equivalent/winter-equivalent returns were -115.25%/-43.26%; high-/low-volatility returns were -76.31%/-82.20%. Both long and short results are persisted separately. The signal timestamps are in the intended 07:00–16:00 UTC session, but there is strong pair and period dependence.

TEST cost stress returns/PFs: 3 bps -27.60%/1.3245; 5 bps -44.74%/1.0867; 8 bps -70.45%/0.8238; 12 bps -104.73%/0.5881. Doubled spread and slippage are negative; +1 H1 delay remains negative (-20.27%). Removing the best trade reduces PF to 1.0236; removing the best three to 0.8258. USDJPY supplies 94.78% of gross profit. Best/best-three trade concentration is 92.74%/153.68% of aggregate net profit, failing 15%/30% caps.

## Classification

**1 REJECT STRATEGY FAMILY**

This single classification is based on `aggregate_cross_pair_test`: although PF and trade-count gates pass, return (-27.60%), robustness (0), and score (24.60) fail; only one pair is positive; 5 bps, breadth, concentration, nearby/period stability, and gross-profit contribution gates also fail. It is not called profitable.

Safety: `paper_only=true`; `ALLOW_LIVE_ORDERS=false`; acceptance gates unchanged; no watcher activation, endpoint call, order, live bridge change, or forward-ledger change; no credentials; no source merging or data fabrication.
