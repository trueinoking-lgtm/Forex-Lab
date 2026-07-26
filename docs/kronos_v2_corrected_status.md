# Kronos Phase 1 V2 — Corrected Status Report

## Correction Applied to Previous Reports

The previous reports (commits `ed6b213` and prior) incorrectly labeled development and validation stages as "PASSED."
This is retracted.

## Actual Status (as of this correction)

### What Was Executed
- Hash guards verified ✅ (all 6 separate hashes checked)
- Data-visibility boundaries enforced ✅
- Origin counts verified ✅ (2608 dev, 302 val)

### What Was NOT Executed
- ❌ No Kronos inference was run
- ❌ No baseline inference was run
- ❌ No scoring/metrics were calculated
- ❌ Development evaluation has NOT started
- ❌ Validation evaluation has NOT started
- ❌ Sealed test remains untouched
- ❌ No predictions, baselines, or metric artifacts exist

### Current Runner Behavior
`run_stage()` in `engine/run_phase1_v2_benchmark.py` performs:
1. All 6 hash guard verifications
2. Data-visibility boundary enforcement
3. Origin counting
4. Returns origin list (no inference, no scoring)

The `score_one_forecast()` utility function exists at line 500 but is never invoked by `run_stage()`.
The `all_scoring` and `all_baseline` lists (lines 635-636) are initialized but never populated.

## Frozen Hashes

| Identifier | Value |
|---|---|
| CODE_COMMIT | **NOT YET FROZEN** |
| CONFIG_SHA256 | `67efce2f895cd333eba9df925419bd37462ecfbb7084f94bdf122cadad338654` |
| DATASET_MANIFEST_SHA256 | `8d30a045359e85966a4a11ddc31a04f54e7e4307368090971622b75f878e7c85` |
| FOLD_MANIFEST_SHA256 | `7cc8b560bd51a6cb45ada146f1e96ee7226b8ca36e0584821d5ff635696fb556` |
| METRIC_SPEC_SHA256 | `5fc92c4a2d43ed2757d4ffab9ad720b87472e56f6f54cde6fd6065769a78611b` |
| ORIGIN_MANIFEST_SHA256 | `2796b2fb7dce21c490fcc2829e2e50ac515812c0ba41ac1b631487318baef102` |

## Pending
No new CODE_COMMIT may be assigned until implementation, replay, evidence, and
tests are complete and committed. Real development, validation, and sealed-test
inference remain prohibited pending performance-gate approval.

## D1 data-path audit

The dataset manifest expects the four files at
`engine/data/raw_mt5_<PAIR>_1d_v2.csv`. As of 2026-07-26, none exists in either
`/root/aether-forex-lab` or `/root/aether-forex-lab-kronos-v2-run`. They are not
tracked by Git and no commit in the repository contains them.

The tracked origin manifest was generated on 2026-07-25 and records the exact
SHA-256 values found in the dataset manifest. Therefore origin counting read
those exact, untracked local files while they were present in the execution
environment. The files were subsequently removed (or were never copied into the
current worktrees). The counts remain committed as JSON, but the source bytes
needed by current production-data tests do not. This is why earlier runs could
count origins while current production-data loading fails.

Synthetic implementation tests do not use these manifests or CSVs. They create
four deterministic OHLC files and all associated manifests under `tmp_path`.

## Import limitation

The public `engine.kronos_adapter` package and benchmark runner are importable
from the repository root without changing `sys.path`. The untouched upstream
`engine/kronos_adapter/model_src/kronos.py` still contains legacy path mutation;
that module is not imported until the real predictor is lazily loaded.
