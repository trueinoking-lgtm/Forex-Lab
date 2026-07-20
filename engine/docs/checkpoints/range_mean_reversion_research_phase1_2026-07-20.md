# Range mean-reversion research — Phase 1 accounting reconciliation (2026-07-20)

Research/paper/demo only. Frozen RSI parameters; no strategy implementation or tuning.

Dataset: `4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2`. Canonical cost: spread 2 bps + slippage 1 bps + commission 0 bps.

The previous PF 1.43 was a full-history diagnostic produced by a mismatched reporting path; it was not OOS and did not clear all four canonical gates.

## Root-cause reconciliation

- D1 — **reporting-label defect**: corrected scope/gate labeling.
- D2 — **lifecycle-ledger mismatch**: range reporting now subsets the same canonical closed-trade ledger.
- D3 — **stale artifact**: 0.81 was from another subfamily, while frozen RSI canonical and 3 bps stress both use identical 2/1/0 bps components.

## Corrected results

| scope | trades | gross profit | gross loss | lifecycle PF | return | robustness | score | all gates |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| development | 87 | 34580.469901 | 20007.768816 | 1.7284 | -0.0491 | 0.000 | 50.14 | False |
| validation | 22 | 9268.918246 | 8287.237142 | 1.1185 | -0.0556 | 0.000 | 30.56 | False |
| chronological_test | 29 | 6675.404791 | 6781.261958 | 0.9844 | -0.0581 | 0.000 | 28.19 | False |
| aggregate_walk_forward_test | 21 | 5189.830155 | 6085.873462 | 0.8528 | -0.0431 | 0.167 | 25.96 | False |
| full_historical_diagnostic | 144 | 51865.376500 | 35727.637939 | 1.4517 | -0.1388 | 0.000 | 40.45 | False |
| regime_range | 144 | 51865.376500 | 35727.637939 | 1.4517 | -0.1388 | 0.000 | 40.45 | False |
| cost_stress:3bps | 144 | 51865.376500 | 35727.637939 | 1.4517 | -0.1388 | 0.000 | 40.45 | False |
| cost_stress:5bps | 144 | 50125.376500 | 36867.637939 | 1.3596 | -0.1871 | 0.000 | 37.20 | False |
| cost_stress:8bps | 144 | 47539.199372 | 38601.460810 | 1.2315 | -0.2544 | 0.000 | 33.61 | False |
| cost_stress:12bps | 144 | 44191.916747 | 41014.178185 | 1.0775 | -0.3356 | 0.000 | 29.79 | False |
| cost_stress:commission_1bps | 144 | 50995.376500 | 36297.637939 | 1.4049 | -0.1633 | 0.000 | 38.82 | False |
| cost_stress:double_spread | 144 | 50125.376500 | 36867.637939 | 1.3596 | -0.1871 | 0.000 | 37.20 | False |
| cost_stress:double_slippage | 144 | 50995.376500 | 36297.637939 | 1.4049 | -0.1633 | 0.000 | 38.82 | False |
| cost_stress:extra_delay | 144 | 52765.879452 | 39769.211998 | 1.3268 | 0.1177 | 1.000 | 66.91 | True |
| cost_stress:remove_best | 143 | 49852.679809 | 35727.637939 | 1.3954 | -0.1388 | 0.000 | 39.35 | False |
| cost_stress:remove_3_best | 141 | 46463.597358 | 35727.637939 | 1.3005 | -0.1388 | 0.000 | 37.43 | False |

Fold PFs are diagnostic only. Aggregate walk-forward PF is recomputed from concatenated chronological test-fold trades, never averaged.

## Classification

**1 REJECT STRATEGY FAMILY**

This single classification is based only on `aggregate_walk_forward_test`; at least one of its four canonical gates fails. Full-history diagnostics are explicitly ineligible as OOS evidence.

Safety: `paper_only=true`, `allow_live_orders=false`; locked gates unchanged; no order endpoint/call and no order; watcher/forward ledger untouched; no credentials; canonical input unchanged.
