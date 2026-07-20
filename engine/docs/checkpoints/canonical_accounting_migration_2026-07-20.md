# Canonical accounting migration and global rebaseline — 2026-07-20

## Decision

**1 BEGIN NEW STRATEGY RESEARCH.** This authorizes research only, not watcher or execution activation. All results below use `normalized_equal_risk_v1` version 2, units are explicit, registry identities are versioned, historical reports are visibly superseded, the rerun is deterministic, and no accounting inconsistency remains. No strategy is called profitable; every frozen strategy is rejected by at least one unchanged gate.

## Accounting and unit contract

Starting research equity and reporting notional are USD 100,000. `gross_pnl_account_currency` and `net_pnl_account_currency` are USD; `expectancy_account_currency_per_trade` is USD/trade; `expectancy_return_fraction` is expectancy divided by USD 100,000; `return_decimal` is a fraction and `return_percent` is that fraction times 100. `pip_movement`, `r_multiple`, `holding_bars`, and `holding_hours` are respectively pips, R, bars, and hours. Thus session breakout's USD -32.204508/trade is exactly -0.00032204508 per trade, or -0.032204508%, and the two quantities are not interchangeable.

Gross trade PnL is `direction × (exit-entry)/entry × USD 100,000`; bps costs are applied to the same notional. PF is combined positive net PnL divided by absolute combined negative net PnL. Return, expectancy, equity, drawdown, concentration, and PF consume the same closed-trade net-PnL ledger. There is no compounding. Equity cannot fall below zero and entries cease at bankruptcy.

Strategies with an explicit stop (`trend_continuation`, the three range candidates, and `session_breakout`) are labeled `normalized_equal_risk`: one risk unit per trade, stop-distance sizing, at most four concurrent positions and four aggregate risk units, on a fixed reporting basis. Strategies and controls without an explicit stop are labeled `fixed_notional_fixed_exposure`: USD 100,000 notional per lifecycle trade, with aggregate risk undefined. They are not represented as equal-risk. Single-symbol ledgers allow one lifecycle position; the four-pair session ledger allows four.

## Dependency and regeneration map

| Consumer/path | Inputs and exact units | Regenerated artifact |
|---|---|---|
| `src.trade_ledger.extract_trades` | raw prices for signal lifecycle; percentage movement; pips for display; normalized USD PnL and decimal return | global corrected ledger summaries |
| `src.trade_ledger.lifecycle_metrics` | closed-trade USD net PnL, bars | PF, gross USD, USD/trade expectancy, concentration |
| `src.backtest` / `src.metrics` | decimal bar returns | return and drawdown diagnostics |
| `src.canonical_eval` / `src.score` | decimal returns, PF ratio, counts, decimal drawdown | robustness, score, unchanged gates |
| `src.baseline` randomized controls | circular-shifted positions, decimal returns, USD lifecycle PnL | all frozen controls in global JSON |
| research `cost_stress` paths | bps converted to USD on normalized notional | superseded; future artifacts must carry v2 metadata |
| session `aggregate` and pair contribution | combined USD net PnL, never raw price movement or mean PF | four-pair corrected session result |
| experiment registry | accounting model/version, allocation, bankruptcy and metric-unit schema | schema-v2 distinct experiment identity |
| canonical/research JSON and checkpoint consumers | versioned USD PnL and explicitly named decimal/percent fields | `global_rebaseline_corrected.json`, reconciliation JSON, this checkpoint |

Legacy raw-price reconstruction is retained only in reconciliation and explicitly marked `legacy_raw_price_units_v1` version 1. Cross-version comparison emits a warning. Pips and R are descriptive trade attributes only and never enter PF or return.

## Before/after reconciliation and program status

Trade IDs derive only from strategy, symbol, entry timestamp, and direction. Every before/after list was identical; no signal or timestamp changed. Legacy PF below is a deterministic same-trade raw-price reconstruction, not a silent rewrite of accepted historical tables.

| Strategy family | Legacy PF | Corrected PF | Gross profit USD | Gross loss USD | Expectancy USD/trade | Return | Drawdown | Robustness | Score | Trades | Classification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| bollinger_range_reversion | 0.941507 | 0.923958 | 43930.84 | 47546.35 | -25.83 | -3.6155% | -0.0781 | 0.00 | 34.22 | 140 | rejected |
| ema_crossover | 1.059302 | 1.064694 | 132312.48 | 124272.79 | 54.32 | 8.0397% | -0.2112 | 1.00 | 49.27 | 148 | rejected |
| ema_trend_pullback | 0.931833 | 0.914256 | 36199.34 | 39594.33 | -20.83 | -3.3950% | -0.0703 | 0.00 | 27.29 | 163 | rejected |
| london_breakout | 0.676905 | 0.654197 | 3286.38 | 5023.53 | -78.96 | -1.7372% | -0.0241 | 0.00 | 25.71 | 22 | rejected |
| macd_trend_confirmation | 0.859926 | 0.850480 | 194309.66 | 228470.45 | -93.08 | -34.1608% | -0.4270 | 0.00 | 15.84 | 367 | rejected |
| rsi_mean_reversion | 0.876800 | 0.879370 | 81031.26 | 92146.98 | -41.95 | -11.1157% | -0.2572 | 0.00 | 23.57 | 265 | rejected |
| rsi_range_reversion | undefined | undefined | 1717.64 | 0.00 | 1717.64 | 1.7176% | 0.0000 | 0.00 | 0.00 | 1 | rejected |
| session_breakout | 1.757026 | 0.708541 | 67094.16 | 94693.42 | -32.20 | -27.5993% | -0.2924 | 0.00 | 15.85 | 857 | rejected |
| trend_continuation | 1.008850 | 1.033778 | 58288.94 | 56384.38 | 14.21 | 1.9046% | -0.1617 | 1.00 | 46.00 | 134 | rejected |
| zscore_range_reversion | 0.941507 | 0.923958 | 43930.84 | 47546.35 | -25.83 | -3.6155% | -0.0781 | 0.00 | 34.22 | 140 | rejected |

The same artifact also records `no_trade`, `buy_and_hold`, fixed-period momentum, SMA crossover, and EMA circular-shift seeds 7/19/41. Controls are controls, not candidate strategies, and are all classified rejected. Undefined PF means there was no loss denominator; it is not infinity and does not pass the PF gate.

## Migration and safety record

Experiment registry schema is 2. Accounting model/version, capital allocation, notional/risk basis, compounding, bankruptcy, concurrency, and metric-unit schema are identity-bearing, so corrected and legacy experiments cannot overwrite or deduplicate each other. A missing version fails closed; explicitly permitted old payloads remain readable with a legacy warning.

The rerun uses the exact registry defaults, the frozen session parameters (`breakout_buffer=.10`, `target_r=1.5`, `max_holding=session_close`), unchanged folds, next-bar lifecycle convention, costs, and closed-trade rules. D1 SHA-256 is `4c306902…`; H1 SHA-256 values remain `80cc20e9…`, `99a2564a…`, `3aad2f78…`, and `776a10f7…`. Identical reruns produce byte-identical corrected JSON. `paper_only=true`, `allow_live_orders=false`; gates, strategies, datasets, watcher, forward ledger, and all order/execution paths are untouched.
