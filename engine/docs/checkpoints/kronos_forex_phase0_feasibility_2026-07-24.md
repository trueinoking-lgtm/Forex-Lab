SUMMARY: Phase 0 Kronos research task is complete.

Classification: 1. KRONOS PHASE 0 READY — ZERO-SHOT EVALUATION AUTHORISED

All 5 tasks completed successfully:

1. Task 1 (Source/License Audit): ✅
   - Repo: https://github.com/shiyu-coder/Kronos, MIT license
   - Kronos-mini: 4.1M params, context 2048, OHLC + optional volume/amount
   - Checkpoint SHA-256 verified: a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c
   - Model revision f4e68697d9d5aed55cef5c96aabc3376bcad9f81
   - No explicit forex in training/evaluation

2. Task 2 (Isolated Environment): ✅
   - Venv: /root/aether-forex-lab/.venvs/kronos (disk-backed, not /tmp)
   - torch 2.13.0+cpu, numpy 2.4.6, pandas 3.0.5, einops 0.8.1, huggingface_hub 0.33.1, tqdm 4.67.1, safetensors 0.6.2
   - Model loads on CPU, peak RSS ~345 MB
   - No GPU required

3. Task 3 (Data Adapter): ✅
   - engine/kronos_adapter/ created with model code and supporting files
   - Reads canonical D1 CSV, filters OHLC, preserves timestamps
   - Validates chronological ordering, no duplicates, no missing OHLC, high >= max(open, close), low <= min(open, close)

4. Task 4 (EURUSD D1 Smoke Test): ✅
   - Last 261 rows of EURUSD D1: 256 input + 5 held-out
   - Frozen params: T=1.0, top_p=0.9, sample_count=1, seed=20260725
   - Prediction completed in 0.180s
   - Output shape: (5, 6) with OHLC + volume + amount
   - OHLC validity violations: 0
   - Deterministic repeat: True (byte-identical, max diff 0.0)
   - No weekend bars in prediction window (0 Saturday/Sunday)
   - All assertions passed

5. Task 5 (Baseline Evaluation Design): ✅
   - Preregistered plan in checkpoint doc
   - Baselines: last-value, random walk, drift, rolling mean, EMA
   - Metrics: MAE, RMSE, directional accuracy, high/low coverage, OHLC validity, rank correlation
   - Chronological folds only, no final-test leakage

Key finding: Previous failure was an ADAPTER BUG (scalar Timestamp passed instead of pd.Series).
When used correctly with the official API contract, the prediction pipeline succeeds with all invariants met.

No commits made (awaiting review per spec).
No git changes to tracked files.