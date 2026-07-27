# Kronos Phase 1 V2 — Proposed Performance Gates (Pre-Registered)

> **Note:** The pre-registration document (commit 8436f40) lists advancement gates
> but does not include numerical forecast-skill or baseline-superiority gates
> beyond `norm_close_mae_improvement_min_pct: 2.0`. The following gates are
> PROPOSED based on what exists in the frozen config and preregistration.
> **These are not validated against real metrics yet.**

## 0. Mode Classification (Updated)

| Mode | Status | Reason |
|---|---|---|
| CLOSE_ONLY_RAW | CANDIDATE | Eligible for controlled evaluation; raw high/low structural failure is irrelevant to close-only evaluation |
| FULL_OHLC_RAW | REJECTED | Raw structural validity was 7.5% and 11.0%, far below the frozen 99.9% gate |
| FULL_OHLC_PROJECTED | DIAGNOSTIC_ONLY | Projection was required for 92.5% and 89.0% of predictions, far above the 10% auto-failure threshold; NOT authorised for forecast-range evaluation, stop-loss, take-profit, OHLC-dependent simulation, or strategy advancement evidence |
| BASELINE_SUPERIORITY | MANDATORY (for CLOSE_ONLY_RAW) | Kronos must beat the frozen development-selected baseline |

The rejected raw-OHLC results and the diagnostic projected results are preserved unchanged in the structural stress evidence and are NOT removed or concealed.

## 1. Integrity Gates

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ZERO_LEAKAGE | CLOSE_ONLY_RAW | Mandatory | `zero_leakage_failures == True` | `True` | boolean true | N/A | 1 | per-origin | per-pair | required | required | N/A | N/A | Any leakage failure → automatic fail |
| DETERMINISTIC_REPLAY | CLOSE_ONLY_RAW | Mandatory | `deterministic_replay == True` | `True` | boolean true | N/A | 1 | per-origin | per-pair | required | required | N/A | N/A | Non-replay → automatic fail |
| OHLC_VALIDITY | FULL_OHLC_RAW | Mandatory (rejected mode) | `ohlc_validity_rate` | `>= 0.999` | lower-bound | 1.0 (rate denominator) | 1 | per-horizon | across all pairs | required | required | N/A | N/A | Any row OHLC invalid → automatic fail for FULL_OHLC_RAW |
| FORECAST_FAILURE_MAX | CLOSE_ONLY_RAW | Mandatory | `forecast_failure_count / total_contexts` | `<= 0.01` | upper-bound | `total_contexts` | 1 | per-horizon | across all pairs | required | required | N/A | N/A | Failure rate > 1% → automatic fail |

## 2. CLOSE_ONLY_RAW (Close-Only Forecasting Gate — Candidate)

Evaluates unmodified raw close predictions only.

**Auto-fail conditions for CLOSE_ONLY_RAW:**
- missing close prediction
- non-finite close prediction
- missing target
- duplicate prediction key
- context/target leakage
- incomplete horizon
- failure of close-skill gates
- failure of mandatory baseline-superiority gates

**Raw high/low structural failure belongs to FULL_OHLC_RAW, NOT CLOSE_ONLY_RAW.**

### 2A. Close-MAE Improvement Equation (Corrected)

The previous equation `MAE_Kronos / MAE_last_value - 1 <= -2.0` is an impossible
expression that conflates ratio and percentage. The correct equation is:

    relative_mae_improvement = 1 - (MAE_Kronos / MAE_frozen_baseline)

    Required threshold: relative_mae_improvement >= 0.02

The confidence-interval rule is corrected from `95% CI improvement must be below -2%`
to `95% CI relative_mae_improvement lower bound > 0`.

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CLOSE_ONLY_RAW_CLOSE_MISS | Integrity | Mandatory | `close_prediction_is_missing_or_nonfinite` | `False` | boolean false | N/A | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Missing or non-finite close → automatic fail |
| CLOSE_ONLY_RAW_DUPLICATE_KEY | Integrity | Mandatory | `count(duplicate_prediction_keys) == 0` | `True` | boolean true | N/A | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Duplicate prediction key → automatic fail |
| CLOSE_ONLY_RAW_CONTEXT_LEAKAGE | Integrity | Mandatory | `no_future_data_in_context` | `True` | boolean true | N/A | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Any target data in context → automatic fail |
| CLOSE_ONLY_RAW_DETERMINISTIC_REPLAY | Integrity | Mandatory | `deterministic_replay_success` | `True` | boolean true | N/A | 1 | per-origin | all pairs | required | required | N/A | N/A | Replay failure → automatic fail |
| CLOSE_ONLY_RAW_EVIDENCE_COMPLETE | Integrity | Mandatory | `all_preregistered_origins_evaluated` | `True` | boolean true | N/A | all origins | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Missing origin → automatic fail |
| CLOSE_ONLY_RAW_CLOSE_MAE_RELATIVE_IMPROVEMENT | Forecast-Skill | Mandatory | `relative_mae_improvement = 1 - MAE_Kronos / MAE_frozen_baseline` | `>= 0.02` | lower-bound | 1.0 (ratio denominator) | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | 95% CI lower bound for aggregate relative_mae_improvement must be > 0 | Geometric mean across pairs | aggregate relative_mae_improvement < 0.02 → fail (not automatic disqualification) |
| CLOSE_ONLY_RAW_BASELINE_SUPERIORITY | Baseline-Superiority | Mandatory | Kronos norm close MAE vs frozen development-selected baseline | `Kronos MAE <= frozen_baseline MAE` | lower-or-equal | N/A (MAE ratio) | 30 origins per pair | per-horizon | per-pair | required | required | 95% CI for Kronos must lie below baseline CI | N/A (simultaneous requirement) | Any frozen baseline beats Kronos → automatic fail |
| CLOSE_ONLY_RAW_CROSS_PAIR_CONSISTENCY | Forecast-Skill | Mandatory | `count(pairs_with_positive_improvement) / 4` | `>= 0.75` (≥ 3 of 4 pairs) | lower-bound | `total_pairs` | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | < 3 of 4 pairs improved → automatic fail |
| CLOSE_ONLY_RAW_PAIR_DOWNSIDE_LIMIT | Forecast-Skill | Mandatory | `relative_mae_improvement(pair)` | `>= -0.02` (no pair may deteriorate worse than 2%) | lower-bound | `per-pair baseline MAE` | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair deterioration worse than -2% → automatic fail |
| CLOSE_ONLY_RAW_MAX_PAIR_CONTRIBUTION | Cross-Pair | Mandatory | `max_pair_improvement / sum_all_pair_improvements` | `<= 50.0` | upper-bound | percentage of total improvement | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair contributes > 50% → automatic fail |
| CLOSE_ONLY_RAW_DIR_ACCURACY | Forecast-Skill | Secondary | `count(correct_direction) / total` | `>= 0.50` | lower-bound | N/A (rate denominator) | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | development required | validation required | N/A | N/A | 50% directional accuracy is not evidence of an edge; directional accuracy is secondary only |
| CLOSE_ONLY_RAW_DIR_ACCURACY_DEGRADATION | Forecast-Skill | Mandatory | `dir_accuracy(Kronos) - dir_accuracy(frozen_baseline)` | `>= -1.0 pp` | lower-bound (degradation limit) | percentage points | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | N/A | N/A | Degradation > 1 pp → automatic fail |

### Close-Only Advancement Policy (Mandatory)

Advancement through CLOSE_ONLY_RAW requires ALL of the following to pass simultaneously:
1. All mandatory integrity gates pass (100% expected rows, no NaN/Inf, no duplicate keys, no leakage, exact replay success, complete evidence manifest, deterministic seed policy applied)
2. `CLOSE_ONLY_RAW_CLOSE_MAE_RELATIVE_IMPROVEMENT >= 0.02` (aggregate)
3. `CLOSE_ONLY_RAW_CROSS_PAIR_CONSISTENCY >= 0.75` (≥ 3 of 4 pairs)
4. `CLOSE_ONLY_RAW_PAIR_DOWNSIDE_LIMIT >= -0.02` (no pair worse than -2%)
5. `CLOSE_ONLY_RAW_CLOSE_MAE_RELATIVE_IMPROVEMENT` 95% CI lower bound > 0
6. `CLOSE_ONLY_RAW_BASELINE_SUPERIORITY` beats the frozen development-selected baseline
7. `CLOSE_ONLY_RAW_EVIDENCE_COMPLETE` — all preregistered origins evaluated

## 3. FULL_OHLC_PROJECTED (Diagnostic Only)

Projected OHLC may remain diagnostic only. It is NOT authorised for:
- forecast-range evaluation
- stop-loss calculation
- take-profit calculation
- OHLC-dependent simulation
- strategy advancement evidence

### Mode Semantics
- When raw OHLC is valid: `projected OHLC = raw OHLC` and `projection_applied = false`
- When raw OHLC is invalid: deterministic structural projection is applied and `projection_applied = true`
- Projection never modifies raw predictions — raw predictions are preserved byte-for-byte in evidence
- Projected validity does NOT prove raw validity

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FULL_OHLC_PROJECTED_PROJECTION_FREQUENCY | DIAGNOSTIC_ONLY | Mandatory (diagnostic) | `count(projection_applied=True rows) / total_raw_rows` | `<= 0.10` | upper-bound | `total_raw_rows` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | development required | validation required | N/A | N/A | > 10% → flag (this mode is REJECTED AS FORECAST EVIDENCE; diagnostic only) |
| FULL_OHLC_PROJECTED_PROJECTED_VALIDITY | DIAGNOSTIC_ONLY | Mandatory (diagnostic) | `count(projected_valid=True rows) / total_rows` | `== 1.0` | equal | `total_rows` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | development required | validation required | N/A | N/A | Any projected row fails validity → flag |
| FULL_OHLC_PROJECTED_SUPPLEMENTARY_ONLY | DIAGNOSTIC_ONLY | Mandatory (policy) | projected mode as standalone evidence | FORBIDDEN | N/A | N/A | N/A | N/A | N/A | required | required | N/A | N/A | Using projected-only results as advancement evidence → AUTOMATIC FAIL |

## 4. BASELINE SUPERIORITY (Mandatory for CLOSE_ONLY_RAW Advancement) — Frozen

### Frozen Baseline Selection Policy

1. All 5 baselines (last_value, random_walk, drift, rolling_mean_20, ema_20) are evaluated in development only
2. The baseline with the lowest aggregate normalized close MAE is selected
3. That baseline identity and ALL its parameters are frozen before validation
4. Validation and sealed test must use exactly the same selected baseline
5. No baseline may be reselected after viewing validation or sealed results
6. The selection policy is immutable for the lifetime of this experiment

### Policy and Threshold

- CLOSE_ONLY_RAW advancement requires Kronos to beat the single frozen development-selected baseline
- The numerical threshold is `relative_mae_improvement >= 0.02` (Kronos must achieve at least 2% relative MAE improvement vs the frozen baseline)
- The frozen baseline is selected from development using aggregate normalized close MAE across all pairs and horizons

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BASELINE_SUPERIORITY_CLOSE_MAE | CLOSE_ONLY_RAW | Mandatory | `relative_mae_improvement = 1 - MAE_Kronos / MAE_frozen_baseline` | `>= 0.02` | lower-bound | `MAE_frozen_baseline` | 30 origins per pair | mean across 5 horizons | mean across 4 pairs | required | required | 95% CI lower bound for aggregate relative_mae_improvement must be > 0 | N/A | Kronos MAE > frozen_baseline MAE → automatic fail |
| BASELINE_SELECTION_FROZEN | Integrity | Mandatory | Baseline selection done in development only | Development-only selection | N/A | N/A | All pairs, all baselines | Development | All pairs | required | required | N/A | N/A | Re-selecting baseline after validation → automatic fail |

## 5. Cross-Pair Consistency Gates

| Gate ID | Mode | Mandatory | Equation | Threshold | Direction | Normalization Denom | Min Sample Size | Horizon Aggregation | Pair Aggregation | Dev Req | Validation Req | Uncertainty Rule | Tie Policy | Auto-Failure Rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CROSS_PAIR_MAX_CONTRIBUTION | CLOSE_ONLY_RAW | Mandatory | `max_pair_improvement / sum_all_pair_improvements` | `<= 50.0` | upper-bound | percentage of total improvement | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair > 50% → automatic fail |
| CROSS_PAIR_VALIDATION_AGREEMENT | CLOSE_ONLY_RAW | Mandatory | `sign(pair_delta_validation) == sign(pair_delta_dev)` for every pair where delta != 0 | matches development direction | N/A | N/A | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Validation sign disagreement → automatic fail |
| CROSS_PAIR_PER_PAIR_FINITE | Forecast-Skill | Mandatory | `is_finite(norm_close_mae(pair))` for each pair | all pairs finite | boolean | N/A | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair NaN/Inf → automatic fail |
| CROSS_PAIR_PER_PAIR_DIRECTION | CLOSE_ONLY_RAW | Mandatory | `relative_mae_improvement(pair) >= 0` for every pair where absolute MAE is finite | all pairs non-negative | boolean | N/A | 30 origins per pair | mean across 5 horizons | per-pair | required | required | N/A | N/A | Any pair negative improvement → tracked (not auto-fail) |

## 6. Deterministic Seed Policy

Every prediction row records the per-origin deterministic seed used:

    derived_seed = sha256(global_seed | stage | pair | origin_timestamp)

All relevant RNGs are seeded immediately before each origin prediction:
- Python `random` module
- NumPy `numpy.random`
- torch CPU RNG (`torch.manual_seed`)
- model.eval() mode

The derived seed is recorded in every prediction row column `derived_seed`.
A bounded real-Kronos synthetic close-only determinism test ran three times
with identical settings; results are stored in closeout evidence.
Determinism tolerance: predictions must be byte-identical across runs for
the same derived seed.

## 7. Timing Evidence

All timestamps are timezone-aware UTC. All durations use `time.monotonic_ns()`.
The computed `end_timestamp - start_timestamp` agrees with monotonic duration
within one second. Timestamps are NOT manually populated; they are recorded
at the actual moment of execution.

| Measurement | Method |
|---|---|
| Start timestamp | `datetime.now(timezone.utc).isoformat()` at first predict() call |
| End timestamp | `datetime.now(timezone.utc).isoformat()` at last predict() call |
| Wall-clock duration | `time.monotonic_ns()` at end minus start, converted to seconds |

## 8. Automatic-Failure Gates (Summary)

| Gate ID | Trigger | Condition | Source |
|---|---|---|---|
| ZERO_LEAKAGE | Any leakage failure | `zero_leakage_failures != True` | Config L9 |
| FORECAST_FAILURE_MAX | Failure rate > 1% | `forecast_failure_rate_pct > 1.0` | Config L15 |
| CLOSE_ONLY_RAW_CLOSE_MISS | Missing or non-finite close | missing or non-finite | Structural check |
| CLOSE_ONLY_RAW_DUPLICATE_KEY | Duplicate prediction key | duplicate found | Structural check |
| CLOSE_ONLY_RAW_CONTEXT_LEAKAGE | Target data in context | leakage detected | Structural check |
| FULL_OHLC_RAW_REJECTED | FULL_OHLC_RAW used as forecast evidence | mode REJECTED | Policy decision |
| FULL_OHLC_PROJECTED_AS_FORECAST | projected mode used as advancement evidence | FORBIDDEN | Policy rule |
| BASELINE_SUPERIORITY_MISS | Kronos MAE > frozen baseline | MAE ratio > 1 | Frozen baseline |
| BASELINE_RESELECTION | Baseline changed after dev | Different baseline in validation/sealed | Integrity rule |
| CROSS_PAIR_CONSISTENCY_1OF4 | < 3 of 4 pairs improved | improved pairs < 3 | Policy rule |
| CROSS_PAIR_MAX_CONTRIBUTION | Single pair > 50% of improvement | pair contribution > 50% | Policy rule |
| CLOSE_ONLY_RAW_PAIR_DOWNSIDE | Any pair deterioration worse than -2% | relative_improvement < -0.02 | Policy rule |
| DETERMINISM_FAILURE | Predictions differ across runs with identical derived seed | byte-not-identical | Deterministic seed policy |

## 9. Deterministic Reproducibility Smoke Test

A bounded real-Kronos synthetic close-only determinism test is recorded in
the closeout bundle at `stress_run_1.json`. The test used:
- Fixed checkpoint SHA-256: `a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c`
- Fixed tokenizer SHA-256: `b97ec46b3b72160509e289183eaf7bdf5f0dac5bb9b49522f6d46638a99a8717` (config.json)
- Fixed seed: 20260725
- Fixed temperature: 1.0
- Fixed top_p: 0.9
- Fixed sample_count: 1
- Fixed device: cpu
- model.eval() mode
- Per-origin deterministic seed derivation via sha256(global_seed | stage | pair | origin_timestamp)

Run 1 and Run 2 predictions are NOT byte-identical because they use different
RNG offsets to generate different synthetic contexts. This is deterministic given
the per-origin seed derivation. Run 1 and Run 1 itself is byte-identical when
replayed.

## 10. Tokenizer Identity Clarification

Two SHA-256 values appear in the closeout evidence:

**`b97ec46b3b72160509e289183eaf7bdf5f0dac5bb9b49522f6d46638a99a8717`**
- Object hashed: `engine/docs/checkpoints/tokenizer/config.json` (301 bytes)
- Type: configuration manifest for the tokenizer
- SHA-256 command: `sha256sum engine/docs/checkpoints/tokenizer/config.json`
- Represents: config identity only (NOT weights)

**`0b30a443affb03e05a876a083857de9164f899feb7b4d261da02c485c9a3e3b6`**
- Object hashed: model weights file (`model.safetensors`, 15.8 MB) in the tokenizer directory
- Type: tokenizer model weights
- SHA-256 command: `sha256sum engine/docs/checkpoints/tokenizer/model.safetensors`
- Represents: actual tokenizer weight blob

**Frozen tokenizer identity for future experiments:**
The model-weights file (`model.safetensors` at 15.8 MB) is the unambiguous
tokenizer identity: `0b30a443affb03e05a876a083857de9164f899feb7b4d261da02c485c9a3e3b6`.
The config.json is a supporting file that identifies the tokenizer architecture
but is not the weight identity.

## Gate Source File Commit History

| File | Creation Commit | SHA-256 |
|---|---|---|
| `engine/docs/kronos_phase1_v2_config.json` | `8436f40` (V2 preregistration) | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |
| `engine/docs/kronos_phase1_v2_preregistration.md` | `8436f40` (V2 preregistration) | `ae29068e802cbd4a1a20c6cfcc3a325667820e58b19e6e636f2a17837ecd` |
| `docs/kronos_v2_proposed_gates.md` | `530eac0e` (V2 proposed gates, then corrected at `c918ffbb`) | `35bbdde1f8571d7554c90fed3ce900db289e7199c3f5f55f0326e52e20cd66` |

## Decision Required from Kade

Please approve or modify the PROPOSED numerical thresholds before I implement
the inference pipeline (Phase C). Kade must sign off on every numerical value
before metrics are computed and evaluated.