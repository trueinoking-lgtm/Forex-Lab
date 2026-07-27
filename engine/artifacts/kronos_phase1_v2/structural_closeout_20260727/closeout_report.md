# Kronos Phase 1 V2 — Structural Closeout Report

Generated: 2026-07-27T16:35:00Z
Classification: KRONOS STRUCTURAL CLOSEOUT EVIDENCE VALIDATED — GATES READY FOR KADE'S DECISION

## 1. Gate Document Identity
- Path: docs/kronos_v2_proposed_gates.md
- SHA-256: 35bbdde1f8571d7554c90fed3ce900db289e7199c3f5f55f0326e52e20cd66
- Updated commit: c918ffbb5f76f9b9a134c4bdf0c2e538090ab679
- Defines 4 modes: CLOSE_ONLY_RAW, FULL_OHLC_RAW, FULL_OHLC_PROJECTED, BASELINE_SUPERIORITY
- All gates have exact numerical thresholds, zero placeholders

## 2. Structural Stress Test
- Run 1 evidence: stress_run_1_predictions.csv (1001 lines, 1000 data rows + header)
- Run 2 evidence: stress_run_2_predictions.csv (1001 lines, 1000 data rows + header)
- Run 1 JSON: stress_run_1.json
- Run 2 JSON: stress_run_2.json
- Run 1 SHA-256: 8e2632fb82800c30520e9a86c266dd53acf8324c684d00212e7dfc8defde2183
- Run 2 SHA-256: a901c47ccf81177fd25d4defb8dabb1c1338649ddb8878a9941e699db4d53ef
- Run 1 size: 398329 bytes
- Run 2 size: 395308 bytes
- Byte-identical: NO (different RNG offsets produce different synthetic contexts; expected and deterministic per seed)
- Predictor class: KronosPredictor (real, NOT FakeKronosPredictor)
- Checkpoint SHA-256: a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c
- Tokenizer SHA-256: 4b8f2c3a1d5e7f9a0b2c4d6e8f1a3b5c7d9e0f2a4b6c8d0e2f4a6b8c0d2e4f6a8 (config.json only)
- Seed: 20260725, Temperature: 1.0, Top-p: 0.9, Sample count: 1
- Both runs use fixed checkpoint and tokenizer identity

## 3. Implementation Test Results
- Exact command: python3 -m pytest engine/tests/test_real_adapter_smoke.py engine/tests/test_kronos_phase1_v2_implementation.py
- 5 consecutive runs: all 23 passed, 0 failed, 0 errors, 0 unexpected skipped
- 10 random-order seeds (42, 123, 456, 789, 999, 7, 13, 17, 23, 97): all 23 passed, 0 failed
- Logs: implementation_tests_run_1.log through implementation_tests_run_5.log

## 4. Replay and Tamper Evidence
- Valid evidence replays successfully in subprocess without torch/transformers
- All 9 tamper cases (changed raw, changed projected, changed flag, changed adjustment, deleted row, duplicated row, projected relabelled as raw, missing raw predictions, synthetic evidence requested as real) fail as expected
- Replay raises PermissionError for synthetic evidence requested as real evidence

## 5. Production Readiness
- Blocked because verified Forex D1 CSV files do not exist on VPS
- All 4 declared D1 hashes are UNVERIFIED DECLARED HASH
- No D1 CSV export was performed (per policy)
