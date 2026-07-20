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
| development | 87 | 0.427390 | 0.254165 | 1.6815 | -0.0491 | 0.000 | 49.36 | False |
| validation | 22 | 0.101487 | 0.094072 | 1.0788 | -0.0556 | 0.000 | 29.90 | False |
| chronological_test | 29 | 0.074334 | 0.075979 | 0.9783 | -0.0581 | 0.000 | 28.09 | False |
| aggregate_walk_forward_test | 21 | 0.058084 | 0.068390 | 0.8493 | -0.0431 | 0.167 | 25.90 | False |
| full_historical_diagnostic | 144 | 0.617993 | 0.431292 | 1.4329 | -0.1388 | 0.000 | 40.14 | False |
| regime_range | 144 | 0.617993 | 0.431292 | 1.4329 | -0.1388 | 0.000 | 40.14 | False |
| cost_stress:3bps | 144 | 0.617993 | 0.431292 | 1.4329 | -0.1388 | 0.000 | 40.14 | False |
| cost_stress:5bps | 144 | 0.597442 | 0.445054 | 1.3424 | -0.1871 | 0.000 | 36.92 | False |
| cost_stress:8bps | 144 | 0.566877 | 0.465957 | 1.2166 | -0.2544 | 0.000 | 33.36 | False |
| cost_stress:12bps | 144 | 0.527245 | 0.494950 | 1.0652 | -0.3356 | 0.000 | 29.59 | False |
| cost_stress:commission_1bps | 144 | 0.607718 | 0.438173 | 1.3869 | -0.1633 | 0.000 | 38.52 | False |
| cost_stress:double_spread | 144 | 0.597442 | 0.445054 | 1.3424 | -0.1871 | 0.000 | 36.92 | False |
| cost_stress:double_slippage | 144 | 0.607718 | 0.438173 | 1.3869 | -0.1633 | 0.000 | 38.52 | False |
| cost_stress:extra_delay | 144 | 0.627840 | 0.476801 | 1.3168 | 0.1177 | 1.000 | 66.74 | True |
| cost_stress:remove_best | 143 | 0.593407 | 0.431292 | 1.3759 | -0.1388 | 0.000 | 39.02 | False |
| cost_stress:remove_3_best | 141 | 0.548810 | 0.431292 | 1.2725 | -0.1388 | 0.000 | 36.96 | False |

Fold PFs are diagnostic only. Aggregate walk-forward PF is recomputed from concatenated chronological test-fold trades, never averaged.

## Classification

**1 REJECT STRATEGY FAMILY**

This single classification is based only on `aggregate_walk_forward_test`; at least one of its four canonical gates fails. Full-history diagnostics are explicitly ineligible as OOS evidence.

Safety: `paper_only=true`, `allow_live_orders=false`; locked gates unchanged; no order endpoint/call and no order; watcher/forward ledger untouched; no credentials; canonical input unchanged.
