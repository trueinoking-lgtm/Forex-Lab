# Kronos Phase 1 V2 — Proposed Performance Gates (Pre-Registered)

> **Note:** The pre-registration document (commit 8436f40) lists advancement gates
> but does not include numerical forecast-skill or baseline-superiority gates
> beyond `norm_close_mae_improvement_min_pct: 2.0`. The following gates are
> PROPOSED based on what exists in the frozen config and preregistration.
> **These are not validated against real metrics yet.**

## 1. Integrity Gates

| Gate | Requirement | Source File | Source Line | Source SHA-256 |
|---|---|---|---|---|
| Zero leakage failures | `zero_leakage_failures == True` | `engine/docs/kronos_phase1_v2_config.json` | L9 | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |
| Deterministic replay | `deterministic_replay == True` | `engine/docs/kronos_phase1_v2_config.json` | L10 | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |
| OHLC validity min | `ohlc_validity_min >= 0.999` | `engine/docs/kronos_phase1_v2_config.json` | L11 | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |
| Forecast failure rate max | `max_forecast_failure_rate_pct <= 1.0` | `engine/docs/kronos_phase1_v2_config.json` | L15 | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |

## 2. Forecast-Skill Gates (PROPOSED)

The preregistration lists `norm_close_mae_improvement_min_pct: 2.0` but does
not include minimum absolute accuracy thresholds for directional accuracy,
return MAE, or OHLC validity per pair. These are PROPOSED for Kade's approval:

| Gate | Requirement | Rationale |
|---|---|---|
| Aggregate norm close MAE improvement ≥ 2% vs last value | From frozen config L12 | Preregistered |
| Improvement on ≥ 3 of 4 pairs | From preregistration L78 | Preregistered |
| Directional accuracy not worse by > 1 pp | From preregistration L81 | Preregistered |
| Directional accuracy ≥ 50% (Kronos beats random) | PROPOSED — not preregistered | Needed for a skill floor |
| Aggregate return MAE improvement ≥ 1% vs last value | PROPOSED — not preregistered | Needed for return-skill floor |
| Per-pair norm close MAE finite (no NaN/Inf) | PROPOSED — not preregistered | Guard against broken forecasts |

## 3. Baseline-Superiority Gates (PROPOSED)

The preregistration does not include explicit baseline-superiority gates.
The current config only has Kronos-versus-last-value in the `norm_close_mae_improvement_min_pct` gate.

| Gate | Requirement | Rationale |
|---|---|---|
| Kronos norm close MAE ≤ last-value norm close MAE | Implicit from 2% improvement gate | Derivable |
| Kronos norm close MAE ≤ random-walk norm close MAE | PROPOSED — not preregistered | Needed for true superiority |
| Kronos norm close MAE ≤ drift norm close MAE | PROPOSED — not preregistered | Needed for true superiority |
| Kronos directional accuracy ≥ each baseline | PROPOSED — not preregistered | Needed for directional superiority |

## 4. Cross-Pair Consistency Gates

| Gate | Requirement | Source |
|---|---|---|
| No single pair contributes > 50% of total improvement | Preregistration L80 | `kronos_phase1_v2_preregistration.md` L80 |
| Validation and sealed-test conclusions agree | Preregistration L79 | `kronos_phase1_v2_preregistration.md` L79 |
| Per-pair norm close MAE within 3× of aggregate | PROPOSED — not preregistered | Needed for cross-pair consistency |

## 5. Automatic-Failure Gates

| Gate | Requirement | Source |
|---|---|---|
| Zero leakage failures | `zero_leakage_failures == True` | Config L9 |
| Forecast failure rate ≤ 1% | `max_forecast_failure_rate_pct <= 1.0` | Config L15 |
| Any pair has 0 origins | Automatic fail (no data) | Implied |
| Any pair has NaN metrics | Automatic fail | Implied |
| Directional accuracy < 40% | PROPOSED — not preregistered | Needed for automatic failure |

## Gate Source File Commit History

| File | Creation Commit | SHA-256 |
|---|---|---|
| `engine/docs/kronos_phase1_v2_config.json` | `8436f40` (V2 preregistration) | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |
| `engine/docs/kronos_phase1_v2_preregistration.md` | `8436f40` (V2 preregistration) | `ae29068e802cbd4a1a20c6cfcc3a325667820e58b19e6e636f2a17837ecd` |

## Decision Required from Kade

Please approve or modify the PROPOSED gates before I implement the inference
pipeline (Phase C). Kade must sign off on which gates are final before metrics
are computed and evaluated.