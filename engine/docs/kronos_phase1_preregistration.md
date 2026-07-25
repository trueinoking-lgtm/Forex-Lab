# Task-Summary: Kronos Phase 1 Final Freeze

## What Was Completed

1. **Dataset identifiers preserved** — all four pairs (EURUSD, GBPUSD, USDJPY, AUDUSD) with absolute paths, SHA-256 hashes, row counts, first/final timestamps, and development/validation/test boundaries. All hashes verified from disk and recorded in the preregistration document.

2. **Walk-forward design frozen** — lookback=256, horizon=5, origin spacing=5, non-overlapping five-bar forecast blocks. Total inference calls: 192 (48 origins × 4 pairs, all in development split). Validation and test splits are too short (155 and 125 rows) to produce any origins. Earlier estimate of ~416 was incorrect and corrected to 192.

3. **Baselines frozen** — last value, random walk, drift, rolling mean (window=20), EMA (span=20). All forecast OHLC and undergo same validity checks as Kronos. Repair rules preregistered and applied equally to all models.

4. **Scoring frozen** — only open, high, low, close scored. Volume and amount excluded from scoring, optimisation, and advancement decisions. All metric formulas and aggregate weighting (equal per observation) frozen.

5. **Advancement thresholds frozen** — 10 exact numerical thresholds including: zero leakage failures, zero unrecoverable forecast failures, OHLC validity ≥ 99.9%, ≥ 2% normalized MAE improvement over last-value, improvement on ≥ 3 of 4 pairs, sealed-test agreement, no single pair > 50% of improvement, directional accuracy within 1pp of last-value, failures < 1%. No profitability claims.

6. **Repository freeze** — commit `3e6d52a` created: `research: finalize Kronos zero-shot benchmark preregistration`. Working tree clean except documented untracked files (.cache/, .venvs/, engine/evidence/). Phase 1 preregistration document contains all 10 required sections.

7. **Task summary included** as required.

## Tests and Evidence

- 10 Phase 0 validation tests all PASSED (data validation, timestamp contract, length invariants, no duplicates, monotonicity, no leakage, no weekend, shape, OHLC validity, deterministic replay)
- Phase 2 tests: 18 passed, 7 skipped across policy proxy (15 passed, 0 failed) and broker swap suites (6 passed, 3 skipped bridge offline, 0 failed)
- Dataset SHA-256 hashes verified from disk for all four pairs
- Deterministic repeat confirmed (byte-identical with seed 20260725)
- OHLC validity: zero violations in smoke test

## Commits Created

1. `08dd9db` — `research: freeze Kronos zero-shot feasibility evidence` (Phase 0 evidence)
2. `e3b08a8` — `research: preregister Kronos zero-shot benchmark` (initial Phase 1 prereg)
3. `2fcdaef` — `chore: trim Phase 0 checkpoint to reference documents`
4. `3e6d52a` — `research: finalize Kronos zero-shot benchmark preregistration` (complete Phase 1 prereg)

## What Remains Pending

- Phase 1 benchmark execution (192 inference calls) — NOT YET AUTHORISED
- Baseline implementations (code) — frozen but not written
- Evaluation test suite — frozen but not written
- Fold manifest — frozen parameters but file not created yet
- Deterministic replay test — methodology defined but not executed
- All forecasts, signals, and trading claims are deferred until preregistration is reviewed and benchmark execution is explicitly authorised

## Final Classification

`1. KRONOS PHASE 1 FROZEN AND COMMITTED — BENCHMARK EXECUTION AUTHORISATION READY`