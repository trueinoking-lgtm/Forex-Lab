# Kronos Phase 1 V3 — Frozen Gate Design

These gates are prospective rules informed by disclosed exploratory engineering
lessons. Similarity to a V2 gate is disclosed and does not make V2 evidence
eligible.

## Common uncertainty rule

Use a synchronized paired moving-block bootstrap over chronological origin
vectors, retaining all five horizons. Block length is
`max(10, ceil(cuberoot(n_complete_origins_per_pair)))`; 10,000 resamples; seed
`20260725`; percentile 95% interval. Ordinary IID intervals are forbidden.

| ID | Status | Equation | Threshold / direction | Baseline | Aggregation and sample | Missing/tie/catastrophic policy | Stage requirement | Rationale and V2 disclosure |
|---|---|---|---|---|---|---|---|---|
| V3_ZERO_LEAKAGE | Primary integrity | `count(max(x_ts)>=min(y_ts) or target outside split)` | `==0` | N/A | Per origin; all pairs; ≥100 origins/pair final | Any failure closed | Dev, validation, final mandatory | Universal temporal validity; resembled V2 because leakage control is methodological. |
| V3_COMPLETE_COVERAGE | Primary integrity | `valid_unique_aligned_rows/expected_rows` | `==1.0` | N/A | 5 rows/origin; equal four-pair scope; ≥2,000 final rows | No imputation, deletion, or retry substitution; ties N/A | All stages mandatory | Prevents informative missingness; stricter than V2's 1% allowance. |
| V3_DETERMINISTIC_REPLAY | Primary integrity | Replayed ledgers, metrics, bootstrap draws, decision | byte-identical | N/A | Entire stage evidence | Any mismatch fails | All stages mandatory | Auditability; resembles V2 for general reproducibility. |
| V3_HORIZON_IDENTITY | Primary integrity | `len(pred)=5 and unique(index)=5 and index=y_timestamp` | all origins true | N/A | Per origin | Any malformed row fails | All stages mandatory | Explicitly informed by Run A's horizon-collapse defect, not its outcomes. |
| V3_AGG_NMAE_SUPERIORITY | Primary forecasting | `L=abs(pred-actual)/abs(origin_close)`; `Delta=equal_pair_mean(L_K-L_B)` | `Delta<0` and bootstrap 95% upper bound `<0`; lower better | One frozen dev-selected baseline | Mean 5 horizons within origin, origins within pair, equal mean of 4 pairs; ≥100 origins/pair | Equality or CI endpoint 0 fails; missing fails | Validation and final mandatory; dev reported | Generic strict paired superiority. Does not copy V2's result-responsive 2% floor. |
| V3_PAIR_CONSISTENCY | Primary forecasting | `count(Delta_pair<0)` | `>=3 of 4`; higher better | Same frozen baseline | Pair mean across origins/horizons; ≥100/pair | Zero effect is not improved | Validation/final mandatory | Predeclared supermajority; resembles V2 and is retained as a general concentration guard, not fitted to Run A. |
| V3_CATASTROPHIC_PAIR | Primary forecasting | `R_pair=Delta_pair/mean(L_B,pair)` | every pair `<=0.10`; lower better | Same frozen baseline | Per pair; ≥100/pair | Invalid denominator fails; equality at 0.10 passes | Validation/final mandatory | General risk cap. V2 used 2%; this 10% policy judgment requires approval independent of Run A. |
| V3_DIRECTIONAL_ADVANCEMENT | Mandatory for advancement into trading-signal research | `DA=mean(sign(pred-origin)==sign(actual-origin))` | `DA>0.5` and bootstrap 95% lower bound of `DA-0.5>0`; higher better | Chance 0.5 | Equal pair weight; ≥100/pair | Exactly 0.5 fails; zero actual is correct only if predicted zero; missing fails | Evaluated only after primary forecasting result; mandatory only for trading-signal-research advancement | Chance-exceeding skill with dependence control. Similar to V2's directional diagnostic but does not redefine forecast superiority. |
| V3_BASELINE_FREEZE | Primary integrity | `argmin` aggregate dev NMAE over four deterministic candidates | winner fixed before validation | Candidate set below | Equal pair weights; all complete dev origins | Frozen lexical tie order | Dev selects once; validation/final cannot reselect | Standard non-oracle nested selection; resembles amended V2 methodologically. |
| V3_NO_POST_FREEZE_CHANGE | Automatic disqualifier | Authorised hashes and protocol fields match | exact equality | N/A | Whole study | Any mismatch invalidates | Before every stage | Required for prospective status. |
| V3_RAW_OHLC_VALIDITY | Diagnostic | `mean(high>=max(open,close) and low<=min(open,close))` | report only | N/A | Per horizon/pair/aggregate | Missing handled by coverage | Diagnostic all stages | V2's structural threshold was result-responsive; V3 does not gate close forecasting on it. |

## Point-baseline candidates

1. `last_value`: `forecast_h=origin_close`.
2. `drift`: `d=mean(diff(context_close_256))`;
   `forecast_h=origin_close+h*d`.
3. `rolling_mean_20`: `forecast_h=mean(last_20_context_closes)`.
4. `ema_20`: `forecast_h=last(EMA(context_close_256,span=20,adjust=false))`.

Select the lowest equal-pair aggregate development normalized close MAE. Tie
order is exactly the order above. Freeze before validation; never reselect.

A stochastic single random-walk path is excluded from point-baseline
competition. Zero-drift random-walk expected value equals `last_value`.
Random walk may be diagnostic only using CRPS, 10,000 Monte Carlo paths, and
seed `20260725`.
