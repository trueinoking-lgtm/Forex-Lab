# Kronos Phase 1 — Final Preregistration (Complete)
# Frozen: 2026-07-25
# Status: AWAITING BENCHMARK EXECUTION

This document replaces all prior preregistration versions.

## 1. Dataset Manifest

### EURUSD
| Field | Value |
|---|---|
| Absolute path | `/root/aether-forex-lab/data/yf_EURUSD=X_1d.csv` |
| SHA-256 | `ce58f0bd2b8b5dbac7b614665a916a8852449651ae317c08db82e2062744b11c` |
| Row count | 778 |
| First timestamp | 2023-07-26 00:00:00+00:00 |
| Final timestamp | 2026-07-24 00:00:00+00:00 |
| Development rows | 0–496 (497 rows) |
| Validation rows | 497–652 (156 rows) |
| Sealed test rows | 653–777 (125 rows) |

### GBPUSD
| Field | Value |
|---|---|
| Absolute path | `/root/aether-forex-lab/engine/data/yf_GBPUSD=X_1d.csv` |
| SHA-256 | `ab34222eed20f8bd3441a40e2ef889f2c770ac71e1c18f7e0d1ec4c614b879b6` |
| Row count | 777 |
| First timestamp | 2023-07-24 00:00:00+00:00 |
| Final timestamp | 2026-07-21 00:00:00+00:00 |
| Development rows | 0–496 (497 rows) |
| Validation rows | 497–651 (155 rows) |
| Sealed test rows | 652–776 (125 rows) |

### USDJPY
| Field | Value |
|---|---|
| Absolute path | `/root/aether-forex-lab/engine/data/yf_USDJPY=X_1d.csv` |
| SHA-256 | `0130df58f83430ef323241b5f8a6fa83be491b293863679ed18c7dc55b0600d6` |
| Row count | 777 |
| First timestamp | 2023-07-24 00:00:00+00:00 |
| Final timestamp | 2026-07-21 00:00:00+00:00 |
| Development rows | 0–496 (497 rows) |
| Validation rows | 497–651 (155 rows) |
| Sealed test rows | 652–776 (125 rows) |

### AUDUSD
| Field | Value |
|---|---|
| Absolute path | `/root/aether-forex-lab/engine/data/yf_AUDUSD=X_1d.csv` |
| SHA-256 | `f7e190dceabbee9e581a9c93adb8d4ebe2600d58c59fd655f6e6761fa096fdd0` |
| Row count | 777 |
| First timestamp | 2023-07-24 00:00:00+00:00 |
| Final timestamp | 2026-07-21 00:00:00+00:00 |
| Development rows | 0–496 (497 rows) |
| Validation rows | 497–651 (155 rows) |
| Sealed test rows | 652–776 (125 rows) |

All SHA-256 values verified from disk. All boundaries are chronological and frozen.

## 2. Frozen Walk-Forward Design

- **lookback = 256 bars**
- **prediction horizon = 5 bars**
- **origin spacing = 5 bars** (non-overlapping five-bar forecast blocks)
- **forecasts do not overlap** — each origin produces a unique 5-bar block
- **all future timestamps come from recorded D1 rows** — no weekend timestamps generated
- **no future data used in preprocessing** — input window is strictly historical

### Origin Count Calculation

For each split, origins = max(0, floor((split_rows - lookback - horizon) / spacing) + 1):

| Pair | Split | Rows | Origins |
|---|---|---|---|
| EURUSD | Development | 497 | 48 |
| EURUSD | Validation | 156 | 0 |
| EURUSD | Test | 125 | 0 |
| GBPUSD | Development | 497 | 48 |
| GBPUSD | Validation | 155 | 0 |
| GBPUSD | Test | 125 | 0 |
| USDJPY | Development | 497 | 48 |
| USDJPY | Validation | 155 | 0 |
| USDJPY | Test | 125 | 0 |
| AUDUSD | Development | 497 | 48 |
| AUDUSD | Validation | 155 | 0 |
| AUDUSD | Test | 125 | 0 |

**Total Kronos inference calls: 192** (48 origins × 4 pairs)

### Why 192, not 416

The earlier estimate of ~416 was incorrect. It assumed 48 origins in development plus additional origins in validation and test splits. With the frozen split boundaries (development has 497 rows, validation has 155–156, test has 125), only the development split has enough rows for a 256+5=261 bar requirement. Validation and test splits are too short (155 and 125 rows respectively) to produce any origins with spacing=5.

Each origin call produces a 5-row forecast. The total forecast ledger contains 192 × 5 = 960 rows.

## 3. Frozen Baselines

All baselines forecast OHLC (open, high, low, close). Each baseline candle undergoes the same OHLC validity checks as Kronos.

### Baseline 1: Last Value
```
forecast_open[t] = actual_open[t-1]
forecast_high[t]  = actual_high[t-1]
forecast_low[t]   = actual_low[t-1]
forecast_close[t] = actual_close[t-1]
```

### Baseline 2: Random Walk
```
sigma = std(log(actual_close[t-1] / actual_close[t-2])) over training window
forecast_open[t]  = actual_open[t-1] * exp(N(0, sigma^2))
forecast_high[t]  = actual_high[t-1] * exp(N(0, sigma^2))
forecast_low[t]   = actual_low[t-1]  * exp(N(0, sigma^2))
forecast_close[t] = actual_close[t-1] * exp(N(0, sigma^2))
```

### Baseline 3: Drift
```
drift = mean(actual_close[t-1] / actual_close[t-2] - 1) over training window
forecast_open[t]  = actual_open[t-1]  * (1 + drift)
forecast_high[t]  = actual_high[t-1]  * (1 + drift)
forecast_low[t]   = actual_low[t-1]   * (1 + drift)
forecast_close[t] = actual_close[t-1] * (1 + drift)
```

### Baseline 4: Rolling Mean (window=20)
```
rolling_mean_open  = mean(actual_open[-20:])
rolling_mean_high  = mean(actual_high[-20:])
rolling_mean_low   = mean(actual_low[-20:])
rolling_mean_close = mean(actual_close[-20:])
forecast_open[t] = rolling_mean_open
forecast_high[t] = rolling_mean_high
forecast_low[t]  = rolling_mean_low
forecast_close[t] = rolling_mean_close
```

### Baseline 5: EMA (span=20)
```
ema_open  = EMA(actual_open, span=20)
ema_high  = EMA(actual_high, span=20)
ema_low   = EMA(actual_low, span=20)
ema_close = EMA(actual_close, span=20)
forecast_open[t] = ema_open
forecast_high[t] = ema_high
forecast_low[t]  = ema_low
forecast_close[t] = ema_close
```

### Baseline OHLC Validity Checks (Preregistered)
- If high < max(open, close): repair high = max(open, close) for ALL models equally
- If low > min(open, close): repair low = min(open, close) for ALL models equally
- Same repair rule applied to Kronos and all baselines (preregistered, no post-hoc tuning)

## 4. Frozen Scoring Policy

### Scored Columns
- open, high, low, close (only Kronos model outputs in these columns)

### Not Scored
- volume (synthetic, mean ≈ 0 in Kronos output)
- amount (synthetic, mean ≈ 0 in Kronos output)

Volume and amount are preserved as labelled raw model outputs for audit only. They are never used for scoring, optimisation, or advancement decisions.

### Metric Formulas

**close MAE** = mean(|pred_close_i - actual_close_i|) over all forecast observations

**close RMSE** = sqrt(mean((pred_close_i - actual_close_i)^2)) over all forecast observations

**normalized close MAE** = close MAE / mean(|actual_close_i - actual_close_{i-1}|) per evaluation split per pair
- Denominator: mean absolute close-to-close movement in the evaluation split
- Normalizes across pairs with different price levels
- Frozen denominator: computed once per split, never recalculated after seeing results

**return MAE** = mean(|pred_return_i - actual_return_i|) where return_i = log(close_i / close_{i-1})

**directional accuracy** = mean(sign(pred_return_i) == sign(actual_return_i)) over all forecast observations

**high/low interval coverage** = mean(actual_close_i in [pred_low_i, pred_high_i]) over all forecast observations

**OHLC validity rate** = mean(all rows satisfy high >= max(open, close) AND low <= min(open, close) AND high >= low) over all forecast observations

### Aggregate Weighting
- **Equal weight per forecast observation** (not per pair, not per fold)
- Aggregate metric = mean of all observations across all 4 pairs × all folds × all horizons
- This gives equal weight to each forecast regardless of which pair or fold it came from

## 5. Frozen Statistical Comparison

- Uncertainty intervals: bootstrap percentile confidence intervals (1000 resamples) by origin
- Paired comparison against last-value baseline: paired t-test on per-origin errors
- Serial dependence treatment: block bootstrap with block size = forecast horizon (5)
- Multiple pairs, horizons, metrics: Bonferroni correction applied
- Significance level: alpha = 0.05 (two-sided)
- Minimum practical improvement threshold: 2% reduction in aggregate normalized close MAE over last-value (as specified in the advancement rule, section 5)

## 6. Frozen Advancement Thresholds

Kronos advances to trading-interpretation research **only if ALL** of:

1. Zero leakage test failures
2. Zero unrecoverable forecast failures (NaN, inf, all-NA predictions)
3. OHLC validity rate ≥ 99.9% (effectively 100%)
4. Deterministic replay succeeds (byte-identical outputs with same seed)
5. Aggregate normalized close MAE beats last-value by ≥ 2%
6. Improvement occurs on at least 3 of 4 pairs
7. Sealed-test result agrees with validation (both show improvement)
8. No single pair contributes > 50% of aggregate improvement
9. Directional accuracy is not worse than last-value by more than 1 percentage point
10. Forecast failures (NaN, inf, OHLC violation) remain below 1% of total forecasts

**Phase 1 does NOT authorise profitability claims or trading.** Separate authorisation required.

## 7. Repository State After Freeze

### Commits Created
1. `2fcdaef` — `chore: trim Phase 0 checkpoint to reference documents`
2. `e3b08a8` — `research: preregister Kronos zero-shot benchmark`
3. `08dd9db` — `research: freeze Kronos zero-shot feasibility evidence`

### Files Committed in Phase 1 Preregistration Commit (e3b08a8)
- `engine/docs/kronos_phase1_preregistration.md` (complete supplement with all sections above)
- `engine/docs/kronos_phase1_forecast_spec.md` (forecast output clarification)

### Working Tree Status
- Working tree clean except for documented untracked files (.cache/, .venvs/, engine/evidence/)
- Phase 0 checkpoint reference file has a small pending change (not committed — it references documents in the repo, not generated data)

### Key Numbers
- Lookback: 256 bars
- Horizon: 5 bars
- Origin spacing: 5 bars
- Forecasts do NOT overlap
- Total origins: 192 (48 per pair × 4 pairs, all in development split)
- Total Kronos inference calls: 192
- Estimated total forecast rows: 960 (192 × 5)
- Dataset row counts: EURUSD=778 rows, GBPUSD=777 rows, USDJPY=777 rows, AUDUSD=777 rows

## 8. Pending (Not Yet Executed)

- Phase 1 benchmark execution (192 inference calls)
- Fold manifest creation with exact split boundaries
- Baseline implementations (code, not yet written)
- Evaluation test suite (code, not yet written)
- Deterministic replay test
- All forecast generation deferred until preregistration is reviewed and benchmark execution is authorised

No forecasts executed. No signals generated. No orders placed.