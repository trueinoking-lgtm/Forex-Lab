# Kronos Phase 1 — Final Preregistration Supplement
# Frozen: 2026-07-25
# Status: AWAITING REVIEW

## 1. Repository State

Phase 0 commit: 08dd9dbaabb79d5b869bc12d029edba8f100a2fd

Files tracked in Phase 0 commit:
- .gitignore (modified)
- engine/docs/checkpoints/Kronos-mini.model.safetensors
- engine/docs/checkpoints/kronos_forex_phase0_feasibility_2026-07-24.md
- engine/docs/kronos_phase1_config.json
- engine/docs/kronos_phase1_preregistration.md
- engine/kronos_adapter/ (all source files, identical to upstream commit 67b630e67f6a)

Files NOT tracked (excluded by .gitignore):
- engine/evidence/kronos/phase0/* (globally excluded by .gitignore line 34)
- .cache/, .venvs/, models/

Note: Phase 1 preregistration files (kronos_phase1_preregistration.md, kronos_phase1_config.json, kronos_phase1_forecast_spec.md) were inadvertently included in the Phase 0 commit. They should be treated as review artifacts, not as committed Phase 0 evidence.

git status --short returns:
  M  engine/docs/kronos_phase1_preregistration.md
  ?? .cache/
  ?? .venvs/
  ?? engine/docs/kronos_phase1_forecast_spec.md
  ?? engine/evidence/

Working tree is clean except for explicitly documented untracked files.

## 2. Forecast Output Policy (Frozen)

Kronos returns six columns: open, high, low, close, volume, amount.

Phase 1 scoring policy:
- Score only open, high, low, close
- Do NOT use predicted volume or amount as forex targets
- Do NOT treat synthetic volume/amount as real market activity
- Do NOT allow volume or amount into any advancement decision
- Preserve volume and amount only as clearly labelled raw model outputs in audit trails

## 3. Dataset Hashes and Time Boundaries

### EURUSD
- Path: data/yf_EURUSD=X_1d.csv
- SHA-256: ce58f0bd2b8b5dbac7b614665a916a8852449651ae317c08db82e2062744b11c
- First timestamp: 2023-07-26 00:00:00+00:00
- Final timestamp: 2026-07-24 00:00:00+00:00
- Row count: 778
- Development: rows 0–500
- Validation: rows 501–650
- Sealed test: rows 651–778

### GBPUSD
- Path: engine/data/yf_GBPUSD=X_1d.csv
- SHA-256: ab34222eed20f8bd3441a40e2ef889f2c70ac71e1c18f7e0d1ec4c614b879b6
- Row count: 778
- Same split proportions as EURUSD

### USDJPY
- Path: engine/data/yf_USDJPY=X_1d.csv
- SHA-256: 0130df58f83430ef323241b5f8a6fa83be491b293863679ed18c7dc55b0600d6
- Row count: 778
- Same split proportions as EURUSD

### AUDUSD
- Path: engine/data/yf_AUDUSD=X_1d.csv
- SHA-256: f7e190dceabbee9e581a9c93adb8d4ebe2600d58c59fd655f6e6761fa096fdd0
- Row count: 778
- Same split proportions as EURUSD

All boundaries are chronological and frozen before execution.

## 4. Walk-Forward Origin Policy

Primary evaluation:
- lookback = 256
- horizon = 5
- origin spacing = 5 (non-overlapping five-bar forecast blocks)

With spacing = 5:
- No forecast horizons overlap
- Each forecast block is independent
- No need for HAC or block-bootstrap correction for independence
- Number of origins per pair per split: (split_rows - lookback - horizon) / spacing + 1
- EURUSD development (~500 rows): ~51 origins
- EURUSD validation (~150 rows): ~29 origins
- EURUSD test (~128 rows): ~24 origins

Total Kronos inference calls (all pairs, all splits):
- Development: ~51 × 4 = 204
- Validation: ~29 × 4 = 116
- Test: ~24 × 4 = 96
- Total: ~416 inference calls

Each call: ~0.2s → total ~83s CPU

## 5. Baseline Formulas (Frozen)

1. Last value: forecast_open = last_open, forecast_high = last_high, etc. (each column forecasts its own last value)
2. Random walk: forecast = last_value + N(0, sigma_daily) (sigma per pair, computed from training data)
3. Drift: forecast = last_value + mean(daily_return) * horizon
4. Rolling mean (20): forecast = mean(last_20_values) for each column independently
5. EMA (span 20): forecast = EMA_20(last_values) for each column independently

### OHLC Validity for Baselines (Preregistered)
- If high < max(open, close): repair high = max(open, close) for all models equally
- If low > min(open, close): repair low = min(open, close) for all models equally
- Same repair rule applied to Kronos and all baselines (preregistered)

## 6. Metric Formulas

- close_MAE = mean(|pred_close - actual_close|)
- close_RMSE = sqrt(mean((pred_close - actual_close)^2))
- normalized_close_MAE = MAE / mean(|actual_close[i] - actual_close[i-1]|) per split, per pair
  - Denominator: mean absolute close-to-close movement in the evaluation split
  - This normalizes across pairs with different price levels
- return_MAE = mean(|pred_return - actual_return|) where return = log(close_t / close_{t-1})
- directional_accuracy = mean(sign(pred_return) == sign(actual_return))
- high_low_coverage = mean(actual_close in [pred_low, pred_high])
- OHLC_validity_rate = mean(all OHLC rows satisfy high >= max(open,close) AND low <= min(open,close) AND high >= low)

### Aggregation Weighting
- Equal weight per forecast observation (not per pair)
- Total metric = mean of all observations across all 4 pairs × all folds × all horizons

## 7. Statistical Comparison

- Uncertainty intervals: bootstrap percentile confidence intervals (1000 resamples) by origin
- Paired comparison against last-value: paired t-test on per-origin errors
- Serial dependence: block bootstrap with block size = forecast horizon (5)
- Multiple pairs, horizons, metrics: Bonferroni correction applied
- Significance level: alpha = 0.05 (two-sided)
- Minimum practical improvement: 5% reduction in normalized MAE over last-value
- No advancement on single metric alone

## 8. Advancement Rule (Frozen)

Kronos advances only if ALL of:
1. Zero leakage tests fail
2. All stored forecasts replay deterministically
3. OHLC validity rate >= 99%
4. Aggregate normalized close error improves over last-value by >= 5%
5. Improvement occurs on at least 3 of 4 pairs
6. Validation and sealed test conclusions agree (both show improvement)
7. No single pair contributes > 50% of total improvement
8. Directional accuracy is not materially worse than last-value (within 5 percentage points)
9. Forecast failures (NaN, inf, OHLC violation) remain below 1% of total forecasts

Phase 1 CANNOT claim profitability. Proficiency claims require separate authorization.

## 9. Runtime Plan

- Estimated inference calls: ~416 total (all pairs, all splits)
- Measured seconds per call: ~0.2s (CPU)
- Estimated total CPU runtime: ~83s
- Estimated forecast-ledger size: ~416 rows × 6 columns × 8 bytes ≈ 20 KB (negligible)
- Expected peak RAM: ~400 MB
- Minimum free disk: 1 GB (model cache + forecasts + targets)
- Resumability: checkpoint after each pair completes; resume from last completed pair
- Failure policy: retry once; if second failure, record as failed origin without fabricated data
- No resampling until preferred forecast appears (deterministic with fixed seed)

## 10. Review Package State

Phase 1 preregistration files are in the working tree (not yet committed in final form).
git diff -- engine/docs/kronos_phase1_preregistration.md shows the supplement content.
git diff -- engine/docs/kronos_phase1_config.json shows no diff (unchanged from Phase 0 commit).
git status --short shows the review state clearly.