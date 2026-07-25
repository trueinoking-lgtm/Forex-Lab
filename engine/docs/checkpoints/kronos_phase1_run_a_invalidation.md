# Kronos Phase 1 Run A — Formal Invalidation

**Run ID:** phase1-20260725T152651Z
**Commit:** 92c5564 (research: Phase 1 frozen zero-shot benchmark results)
**Invalidated:** Yes — do not use Run A metrics as evidence for or against Kronos

---

## 1. Reason for Invalidation

Run A violated multiple preregistered constraints and contains compounding evaluator defects:

### 1.1 Wrong Frequency (Critical)
- **Preregistered:** EURUSD D1, GBPUSD D1, USDJPY D1, AUDUSD D1
- **Run A executed against:** `engine/data/raw_mt5_<PAIR>_1h.csv` (H1 files)
- Run A used 102,675-row H1 CSVs instead of D1 bar data.
- Kronos is a timestamp-aware model; H1 provenance is directly relevant.
- Historical broker-server timezone offset policy for these H1 files remains unresolved.

### 1.2 Forecast Collapse Defect (Critical)
- Kronos model output `prediction_df` with `len=5` (one row per forecast horizon).
- The Run A evaluator extracted only `prediction_df.iloc[-1]` and replicated it across all 5 horizons.
- This means horizons 1–4 were scored against predictions for horizon 4, not their own horizon.
- Metric values are meaningless under this collapse.

### 1.3 Directional Accuracy Implementation Defect (Critical)
- Preregistered formula: `sign(predicted_close_h - origin_close)` vs `sign(actual_close_h - origin_close)`
- Run A formula: `sign(diff(predicted_sequence))` vs `sign(diff(actual_sequence))`
- These are not equivalent. The Run A formula measures trend consistency within the forecast, not forecast accuracy relative to the origin.

### 1.4 Validation/Sealed-Test Context Restriction (Major)
- The executor required all 256 context bars to lie inside the target split.
- Standard time-series methodology allows context from earlier splits.
- Under correct methodology, validation has 1,802 valid origins and sealed test has 1,905.
- Run A reported these splits as having insufficient data (155/125 rows) — incorrect reasoning.

### 1.5 Manifest Row Count Inaccuracy
- Manifest claimed: development=76,110 rows, validation=155 rows, sealed-test=125 rows.
- Actual D1 rows (from `data/yf_EURUSD=X_1d.csv`, the only D1 file): 0 dev, 377 val, 397 test.
- Actual H1 rows matching those date ranges: 84,072 dev, 9,012 val, 9,526 test.
- Neither frequency band matches the manifest counts exactly (76,110 ≈ 89% of H1 dev rows — unexplained subset).

### 1.6 OHLC Validity Misstatement
- Run A reported "98.4% validity" and "8.4% of forecasts produced invalid candles."
- These use different denominators (candles vs forecast windows) and ARE simultaneously consistent, but the 8.4% figure was miscalculated as half the true value (actual ~16.7% of forecast windows contained at least one invalid candle).

---

## 2. Evidence That Remains Valid

- Runtime feasibility evidence: model loads, tokenizer works, inference runs end-to-end on CPU
- Model/checkpoint SHA-256 values match Phase 0
- The development-only evaluation completed all 192 inferences without failure
- Deterministic replay verified: stored aggregate metrics are internally consistent with the (flawed) Run A scoring code
- The forecast ledger, baseline ledger, and scoring files are preserved as immutable artifacts

---

## 3. Commit Reference

- **Preserved:** `92c5564` — research: Phase 1 frozen zero-shot benchmark results (untouched)

This invalidation report must be committed as a separate tracked file. The original Run A commit must not be amended, reset, deleted, or overwritten.
