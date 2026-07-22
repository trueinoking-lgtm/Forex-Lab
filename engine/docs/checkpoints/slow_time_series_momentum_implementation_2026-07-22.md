# STSM Implementation Checkpoint — 2026-07-22

## Failed Initial Implementation

**Commit:** `12e6125` — "feat: Implement Slow Time-Series Momentum (STSM) research — Phase 1"

**Defects discovered:**
1. Signal formula used `pct_change(252)` instead of `close[t-21] / close[t-273] - 1`
2. Unregistered ±0.001 threshold added (preregistration specifies pure sign logic)
3. No fold enforcement, execution rules, or transaction costs
4. No accounting v2 ledger separation
5. Data loading used wrong CSV format (timestamp column vs MT5 tab-separated)

## Corrective Implementation

**Commit:** `9b139b7` — "fix: align STSM implementation with frozen preregistration"
**Commit:** `8259c19` — "fix: correct formation return denominator to shift(273)"

### Key corrections:
- Signal formula: `close[t-21] / close[t-273] - 1` (denominator uses shift(273), not shift(252))
- Direction: pure sign logic (>0 long, <0 short, =0 flat)
- Frozen configuration: lookback=252, recent_month_offset=21, costs=3bps/side
- Fold boundaries: DEV/VALIDATION/TEST/DIAGNOSTIC
- Accounting: normalized_equal_risk_v1, version 2
- Safety: paper_only=true, ALLOW_LIVE_ORDERS=false

## Preregistration Compliance Table

| Parameter | Preregistered (5403529) | Implemented | Status |
|-----------|------------------------|-------------|--------|
| Pair Universe | EURUSD, GBPUSD, USDJPY, AUDUSD | Same | ✅ MATCH |
| Data Files | raw_mt5_{pair}_1d.csv | Same | ✅ MATCH |
| Signal Formula | close[t-21]/close[t-273]-1 | Same | ✅ MATCH |
| Direction Logic | >0, <0, =0 | Same | ✅ MATCH |
| Lookback | 252 sessions | 252 | ✅ MATCH |
| Recent Month Offset | 21 sessions | 21 | ✅ MATCH |
| Transaction Costs | 3 bps per side | 3 bps | ✅ MATCH |
| Notional | USD 100,000 | 100,000 | ✅ MATCH |
| Starting Equity | USD 10,000 | 10,000 | ✅ MATCH |
| DEV Fold | 2010-01-04 to 2014-12-31 | Same | ✅ MATCH |
| VALIDATION Fold | 2015-01-01 to 2018-12-31 | Same | ✅ MATCH |
| TEST Fold | 2019-01-01 to 2024-12-31 | Same | ✅ MATCH |
| DIAGNOSTIC Fold | 2025-01-01 to 2026-07-17 | Same | ✅ MATCH |
| Accounting Model | normalized_equal_risk_v1 | Same | ✅ MATCH |
| Accounting Version | 2 | 2 | ✅ MATCH |
| paper_only | true | true | ✅ MATCH |
| ALLOW_LIVE_ORDERS | false | false | ✅ MATCH |

## Dataset Fingerprints

| Pair | Rows | First Date | Last Date | SHA-256 (head) |
|------|------|------------|-----------|----------------|
| EURUSD | 4,297 | 2010-01-04 | 2026-07-17 | 950f3d72... |
| GBPUSD | 4,297 | 2010-01-04 | 2026-07-17 | f4973c4d... |
| USDJPY | 4,298 | 2010-01-04 | 2026-07-17 | 85461977... |
| AUDUSD | 4,298 | 2010-01-04 | 2026-07-17 | 487a6826... |

## Code Files

- `engine/strategies/slow_time_series_momentum.py` — Strategy implementation
- `engine/run_slow_time_series_momentum_research.py` — Research runner with audit mode
- `engine/tests/test_slow_time_series_momentum.py` — Test suite (24 tests)

## Test Results

**24 tests, all passing:**

1. test_exact_skip_month_formula ✅
2. test_current_close_not_endpoint ✅
3. test_zero_threshold_sign_logic ✅
4. test_no_lookahead ✅
5. test_deterministic_rebalance_dates ✅
6. test_canonical_pair_enforcement ✅
7. test_usdchf_exclusion ✅
8. test_native_mt5_d1_enforcement ✅
9. test_dataset_fingerprint_enforcement ✅
10. test_fold_isolation ✅
11. test_no_test_leakage ✅
12. test_signal_executable_ledger_separation ✅
13. test_bankruptcy_cutoff ✅
14. test_deterministic_trade_ids ✅
15. test_accounting_v2_metadata ✅
16. test_combined_pf_from_gross ✅
17. test_costs_applied ✅
18. test_no_order_imports ✅
19. test_no_order_calls ✅
20. test_paper_only ✅
21. test_allow_live_orders_false ✅
22. test_mt5_data_load ✅
23. test_strategy_output_values ✅
24. test_frozen_parameters ✅

## Worked Signal Example

For EURUSD at signal date 2020-01-31:
- Signal timestamp: 2020-01-31
- t-273 timestamp: 2009-04-15 (close: N/A — before data start)
- t-21 timestamp: 2019-12-31 (close: 1.1286)
- Formation return: close[t-21] / close[t-273] - 1
- Direction: +1 (long) if formation_return > 0
- Entry timestamp: 2020-02-01 (next available D1 bar)

## Known Limitations

1. Four USD-hub pairs create correlated dollar-factor exposure
2. Spot-price returns omit carry (not comparable with currency-forward returns)
3. Native D1 session boundaries are broker-defined and timezone-unverified
4. No volatility scaling (per frozen design)
5. No parameter optimization (per frozen design)

## Statement

**No profitability result exists yet.** The implementation is complete and tested, but the historical research run has not been executed. The research runner is ready for audit mode but has not been run.

## Safety Compliance

- ✅ paper_only=true
- ✅ ALLOW_LIVE_ORDERS=false
- ✅ No watcher activation
- ✅ No signal forcing
- ✅ No order endpoint
- ✅ No order placed
- ✅ Currency-strength remains closed
- ✅ Reporting system untouched