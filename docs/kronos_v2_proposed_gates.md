# Kronos Phase 1 V2 — Proposed Performance Gates (Pre-Registered)

> **Note:** The pre-registration document (commit 8436f40) lists advancement gates
> but does not include numerical forecast-skill or baseline-superiority gates
> beyond `norm_close_mae_improvement_min_pct: 2.0`. The following gates are
> PROPOSED based on what exists in the frozen config and preregistration.
> **These are not validated against real metrics yet.**

## 1. Integrity Gates

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ZERO_LEAKAGE | Integrity | Mandatory | `zero_leakage_failures` | `== True` | boolean true | N/A | 1 | per-origin | per-pair | required | required | N/A | N/A | Any leakage failure → automatic fail |
| DETERMINISTIC_REPLAY | Integrity | Mandatory | `deterministic_replay` | `== True` | boolean true | N/A | 1 | per-origin | per-pair | required | required | N/A | N/A | Non-replay → automatic fail |
| OHLC_VALIDITY | Integrity | Mandatory | `ohlc_validity_rate` | `>= 0.999` | lower-bound | 1.0 (rate denominator) | 1 | per-horizon | across all pairs | required | required | N/A | N/A | Any row OHLC invalid → auto fail for FULL_OHLC_RAW |
| FORECAST_FAILURE_MAX | Integrity | Mandatory | `forecast_failure_count / total_contexts` | `<= 0.01` | upper-bound | `total_contexts` | 1 | per-horizon | across all pairs | required | required | N/A | N/A | Failure rate > 1% → automatic fail |

## 2. CLOSE_ONLY_RAW (Close-Only Forecasting Gate)

Evaluates unmodified raw close predictions only. Raw high/low structural failures do NOT disqualify this gate — those belong to FULL_OHLC_RAW.

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CLOSE_ONLY_RAW_CLOSE_S kill | Forecast-Skill | Mandatory | `norm(close_forecast - close_actual) / norm(close_last_value - close_actual)` | `< 1.0` | lower-is-better | `norm(close_last_value - close_actual)` (baseline denominator) | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | 95% CI must lie below threshold | Geometric mean across pairs | Missing close prediction or non-finite close → automatic fail |
| CLOSE_ONLY_RAW_NORM_CLOSE_MAE_IMPROVEMENT | Forecast-Skill | Mandatory | `norm_close_mae(Kronos) / norm_close_mae(last_value) - 1` | `<= -2.0` (i.e., 2% improvement) | upper-bound (more negative is better) | `norm_close_mae(last_value)` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | 95% CI improvement must be below -2% | Geometric mean across pairs | Improvement < 2% → fail, but no automatic disqualification |
| CLOSE_ONLY_RAW_BASELINE_SUPERIORITY | Baseline-Superiority | Mandatory | Kronos norm close MAE vs each baseline | `Kronos MAE <= baseline MAE` for every baseline | lower-or-equal-is-better | N/A (MAE ratio) | 30 origins per pair | per-horizon | per-pair | required | required | Must beat every baseline simultaneously | N/A (simultaneous requirement) | Any baseline beats Kronos → automatic fail |
| CLOSE_ONLY_RAW_PAIR_IMPROVEMENT | Forecast-Skill | Mandatory | `norm_close_mae(Kronos) / norm_close_mae(last_value) - 1` per pair | `<= -2.0` per pair | per-pair improvement | per-pair baseline MAE | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A per pair | N/A | Pairs with < 2% improvement do NOT auto-fail the gate (only tracked for cross-pair consistency) |
| CLOSE_ONLY_RAW_MAX_PAIR_CONTRIBUTION | Cross-Pair | Mandatory | `max_pair_improvement / sum_all_pair_improvements` | `<= 50.0` | upper-bound | percentage of total improvement | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair contributes > 50% → automatic fail |
| CLOSE_ONLY_RAW_DIR_ACCURACY | Forecast-Skill | Secondary | `count(correct_direction) / total` | `>= 0.50` | lower-bound | N/A (rate denominator) | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | development required | validation required | N/A | N/A | Directional accuracy < 40% → automatic fail |
| CLOSE_ONLY_RAW_DIR_ACCURACY_DEGRADATION | Forecast-Skill | Mandatory | `dir_accuracy(Kronos) - dir_accuracy(last_value)` | `>= -1.0 pp` | lower-bound (degradation limit) | percentage points | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Degradation > 1 pp → automatic fail |
| CLOSE_ONLY_RAW_RETURN_MAE_IMPROVEMENT | Forecast-Skill | Secondary | `return_mae(Kronos) / return_mae(last_value) - 1` | `<= -1.0` (1% improvement) | upper-bound (more negative is better) | `return_mae(last_value)` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | development required | validation required | N/A | N/A | Improvement < 1% → tracked but no auto-fail |
| CLOSE_ONLY_RAW_FORECAST_FAILURE_RATE | Forecast-Skill | Mandatory | `forecast_failure_count / total_predictions` | `<= 0.01` | upper-bound | `total_predictions` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Failure rate > 1% → automatic fail |

## 3. FULL_OHLC_RAW (Full OHLC Structural Gate)

Evaluates all 4 raw OHLC fields. Raw high/low structural failures disqualify this gate. CLOSE_ONLY_RAW does NOT check high/low validity.

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FULL_OHLC_RAW_OHLC_VALIDITY | Integrity | Mandatory | `count(valid_rows) / total_rows` where valid means `high >= max(open, close)` AND `low <= min(open, close)` | `>= 0.999` | lower-bound | `total_rows` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Any row where high < max(open, close) OR low > min(open, close) → automatic fail for this gate |
| FULL_OHLC_RAW_NORM_CLOSE_MAE_IMPROVEMENT | Forecast-Skill | Mandatory | `norm_close_mae(Kronos) / norm_close_mae(last_value) - 1` | `<= -2.0` | upper-bound | `norm_close_mae(last_value)` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | 95% CI below -2% | Geometric mean across pairs | Improvement < 2% → fail |
| FULL_OHLC_RAW_BASELINE_SUPERIORITY | Baseline-Superiority | Mandatory | Kronos norm close MAE vs each baseline | `Kronos MAE <= baseline MAE` for every baseline | lower-or-equal | N/A | 30 origins per pair | per-horizon | per-pair | required | required | Beat every baseline | N/A | Any baseline beats Kronos → automatic fail |
| FULL_OHLC_RAW_HI_LO_INTERVAL | Forecast-Skill | Secondary | `count(high_low_covers_actual) / total_rows` | `>= 0.90` | lower-bound | `total_rows` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | development required | validation required | N/A | N/A | Coverage < 90% → tracked, no auto-fail |
| FULL_OHLC_RAW_DIR_ACCURACY | Forecast-Skill | Mandatory | `count(correct_direction) / total` | `>= 0.50` | lower-bound | N/A | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | < 40% → automatic fail |
| FULL_OHLC_RAW_DIR_ACCURACY_DEGRADATION | Forecast-Skill | Mandatory | `dir_accuracy(Kronos) - dir_accuracy(last_value)` | `>= -1.0 pp` | lower-bound (degradation limit) | pp | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Degradation > 1 pp → automatic fail |
| FULL_OHLC_RAW_FORECAST_FAILURE | Forecast-Skill | Mandatory | `forecast_failure_count / total_predictions` | `<= 0.01` | upper-bound | `total_predictions` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | > 1% → automatic fail |
| FULL_OHLC_RAW_MAX_PAIR_CONTRIBUTION | Cross-Pair | Mandatory | `max_pair_improvement / sum_all_pair_improvements` | `<= 50.0` | upper-bound | percentage | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair > 50% contribution → automatic fail |

## 4. FULL_OHLC_PROJECTED (Projected OHL Mode)

Projected OHLC is supplemental to raw OHLC. It exists for every forecast row regardless of raw validity.

### Mode Semantics
- When raw OHLC is valid: `projected OHLC = raw OHLC` and `projection_applied = false`
- When raw OHLC is invalid (high < max(open, close) or low > min(open, close)): deterministic structural projection is applied and `projection_applied = true`
- Projection never modifies raw predictions — raw predictions are preserved byte-for-byte in evidence
- Projected validity does NOT prove raw validity
- Projected mode cannot be used as sole evidence for advancement

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FULL_OHLC_PROJECTED_PROJECTION_FREQUENCY | Integrity | Mandatory | `count(projection_applied=True rows) / total_raw_rows` | `<= 0.05` (5%) | upper-bound | `total_raw_rows` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Projection frequency > 5% → flag (not auto-fail); > 10% → automatic fail |
| FULL_OHLC_PROJECTED_PROJECTED_VALIDITY | Integrity | Mandatory | `count(projected_valid=True rows) / total_rows` | `== 1.0` | equal | `total_rows` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Any projected row fails validity → automatic fail |
| FULL_OHLC_PROJECTED_SUPPLEMENTARY_ONLY | Usage Rule | Mandatory | projected mode as standalone evidence | forbidden | N/A | N/A | N/A | N/A | N/A | required | required | N/A | N/A | Using projected-only results as advancement evidence → automatic fail |
| FULL_OHLC_PROJECTED_CLOSE_CLOSE_TO_RAW | Consistency | Secondary | `count(projected_close == raw_close) / total_rows` | `== 1.0` | equal | N/A (ratio of exact matches) | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | development required | validation required | N/A | N/A | Inconsistency tracked |

## 5. BASELINE SUPERIORITY (Mandatory for CLOSE_ONLY_RAW Advancement)

### Frozen Baseline Selection Policy

1. All 5 baselines (last_value, random_walk, drift, rolling_mean_20, ema_20) are evaluated in development only
2. The development-selected baseline set is frozen once and reused unchanged for validation and sealed test
3. Kronos must improve upon (beat) ALL selected baselines simultaneously
4. The same frozen baselines cannot be re-selected after seeing validation or sealed-test results

### Policy and Threshold

- Advancement requires beating every development-selected baseline
- The numerical threshold for the primary baseline (last_value) is `norm_close_mae_improvement_min_pct = 2.0` (Kronos must achieve at least 2% MAE reduction vs last-value)
- Secondary baselines (random_walk, drift, rolling_mean_20, ema_20) must not be beaten by Kronos (Kronos MAE ≤ baseline MAE)
- Directional accuracy must not degrade by more than 1 pp vs any baseline

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BASELINE_SUPERIORITY_CLOSE_MAE | Baseline | Mandatory | `norm_close_mae(Kronos) / norm_close_mae(baseline_i) - 1` for each baseline | `<= 0` for all baselines, `<= -0.02` for last_value | lower-or-equal | N/A | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | 95% CI for Kronos must lie below baseline | N/A | Kronos MAE > any baseline → automatic fail |
| BASELINE_SUPERIORITY_DIRECTIONAL | Baseline | Mandatory | `dir_accuracy(Kronos) - dir_accuracy(baseline_i)` | `>= 0` for all baselines | lower-or-equal degradation | pp | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Kronos degradation vs any baseline > 0 → tracked; degradation > -1 pp → auto fail |
| BASELINE_SELECTION_FROZEN | Integrity | Mandatory | Baseline selection done in development only | Development-only selection | N/A | N/A | All pairs, all baselines | Development | All pairs | required | required | N/A | N/A | Re-selecting baselines after validation → automatic fail |

## 6. Cross-Pair Consistency Gates

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CROSS_PAIR_MAX_CONTRIBUTION | Cross-Pair | Mandatory | `max_pair_improvement / sum_all_pair_improvements` | `<= 50.0` | upper-bound | percentage of total improvement | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair > 50% → automatic fail |
| CROSS_PAIR_VALIDATION_AGREEMENT | Cross-Pair | Mandatory | `sign(pair_delta_validation) == sign(pair_delta_dev)` for every pair where delta != 0 | matches development direction | N/A | N/A | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Validation sign disagreement → automatic fail |
| CROSS_PAIR_CONSISTENCY_1OF4 | Cross-Pair | Mandatory | `count(pairs_improved) / 4` | `>= 0.75` (≥ 3 of 4 pairs) | lower-bound | `total_pairs` | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | < 3 of 4 pairs improved → automatic fail |
| CROSS_PAIR_PER_PAIR_FINITE | Forecast-Skill | Mandatory | `is_finite(norm_close_mae(pair))` for each pair | all pairs finite | boolean | N/A | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair NaN/Inf → automatic fail |
| CROSS_PAIR_PER_PAIR_WITHIN_3X | Cross-Pair | Secondary | `max_pair_norm_close_mae / min_pair_norm_close_mae` | `<= 3.0` | upper-bound | ratio of norms | 30 origins per pair | mean across 5 horizons | per-pair | development required | validation required | N/A | N/A | 3× spread tracked, no auto-fail |

## 7. Automatic-Failure Gates (Summary)

| Gate ID | Trigger | Condition | Source |
|---|---|---|---|
| ZERO_LEAKAGE | Any leakage failure | `zero_leakage_failures != True` | Config L9 |
| FORECAST_FAILURE_MAX | Failure rate > 1% | `forecast_failure_rate_pct > 1.0` | Config L15 |
| FULL_OHLC_RAW_OHLC_VALIDITY | Any OHLC invalid raw row | OHLC validity < 0.999 or any row invalid | Structural check |
| CLOSE_ONLY_RAW_CLOSE_MISS | Missing or non-finite close prediction | missing or non-finite value | Structural check |
| CLOSE_ONLY_RAW_DIR_ACCURACY | Directional accuracy < 40% | `dir_accuracy < 0.40` | Proposed (not preregistered) |
| BASELINE_SUPERIORITY_MISS | Kronos MAE > any baseline | MAE ratio > 1 for any baseline | Frozen dev baseline |
| BASELINE_RESELECTION | Baselines changed after dev | Different baseline set in validation/sealed | Integrity rule |
| CROSS_PAIR_CONSISTENCY_1OF4 | < 3 of 4 pairs improved | improved pairs < 3 | Preregistration |
| CROSS_PAIR_MAX_CONTRIBUTION | Single pair > 50% of improvement | pair contribution > 50% | Preregistration |
| PROJECTED_SUPERIORITY | Projected-only evidence used as advancement | projection frequency used standalone | Policy rule |

## Gate Source File Commit History

| File | Creation Commit | SHA-256 |
|---|---|---|
| `engine/docs/kronos_phase1_v2_config.json` | `8436f40` (V2 preregistration) | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |
| `engine/docs/kronos_phase1_v2_preregistration.md` | `8436f40` (V2 preregistration) | `ae29068e802cbd4a1a20c6cfcc3a325667820e58b19e6e636f2a17837ecd` |
| `docs/kronos_v2_proposed_gates.md` | `530eac0e` (V2 proposed gates) | `2d3617bb41874ad44db476df80717082650faee51adac9c262a7a66df9f1797c` |

## Decision Required from Kade

Please approve or modify the PROPOSED numerical thresholds before I implement the inference pipeline (Phase C). Kade must sign off on every numerical value before metrics are computed and evaluated.