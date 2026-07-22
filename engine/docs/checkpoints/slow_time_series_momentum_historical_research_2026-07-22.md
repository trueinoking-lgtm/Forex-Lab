# STSM Historical Research Phase 1 — Implementation Checkpoint

## Commit History

| Commit | Type | Description |
|--------|------|-------------|
| `12e6125` | feat | Failed initial implementation (retained for audit) |
| `9b139b7` | fix | Align STSM implementation with frozen preregistration |
| `8259c19` | fix | Correct formation return denominator to shift(273) |
| `c5a3f4e` | test | Add Friday-to-Monday entry verification |
| `02aaa2c` | docs | Record corrected STSM implementation checkpoint |
| `84944d6` | feat | Add STSM executable portfolio accounting |

## Frozen Preregistration

- **Commit:** `5403529`
- **Signal formula:** `close[t-21] / close[t-273] - 1`
- **Direction:** `>0` long, `<0` short, `=0` flat
- **Pair universe:** EURUSD, GBPUSD, USDJPY, AUDUSD
- **Data:** Native MT5 D1 files only
- **Notional:** USD 100,000 per accepted trade (fixed)
- **Starting equity:** USD 10,000 (no compounding)
- **Costs:** 3 bps per side
- **Accounting:** normalized_equal_risk_v1, version 2
- **Safety:** paper_only=true, ALLOW_LIVE_ORDERS=false

## Worked Signal Example (from real data)

Generated from EURUSD data at t=500:

- **Signal timestamp:** 2011-12-05 (t=500)
- **t-273 timestamp:** 2010-11-17 (t=227), close: 1.35294
- **t-21 timestamp:** 2011-11-04 (t=479), close: 1.37898
- **Formation return:** 1.37898 / 1.35294 - 1 = 0.01925
- **Direction:** +1 (long)
- **Entry timestamp:** 2011-12-06 (next available D1 bar)

**Verification:** `close.iloc[479] / close.iloc[227] - 1 = 0.01925` ✅

## Entry Timestamp Verification

Friday signal at 2011-01-21 → Entry at 2011-01-24 (Monday)
Entry uses next available trading bar, not Saturday. ✅

## Dataset Fingerprints

| Pair | File | Rows | First | Last | SHA-256 |
|------|------|------|-------|------|---------|
| EURUSD | `engine/data/raw_mt5_EURUSD_1d.csv` | 4,300 | 2010-01-04 | 2026-07-22 | `f26b72e28ecd4265cb9fe0cbe7772fee12971190015a1d0915998f0a4fc9eaf8` |
| GBPUSD | `engine/data/raw_mt5_GBPUSD_1d.csv` | 4,300 | 2010-01-04 | 2026-07-22 | `13d4340bda0e99a3876aa38c8c818662dbd0f38600128e482876734089ace187` |
| USDJPY | `engine/data/raw_mt5_USDJPY_1d.csv` | 4,301 | 2010-01-04 | 2026-07-22 | `abd384c03bc7257e44f7074601cfcab6acaa1d40240d86b0bd0b1c37bf777ae5` |
| AUDUSD | `engine/data/raw_mt5_AUDUSD_1d.csv` | 4,301 | 2010-01-04 | 2026-07-22 | `32ac5ec0164a6df0cd8ddf3ee594d002861903a8f5f670404dff8ade8a8cd815` |

## ⚠️ INVALIDATED — EXIT-SCHEDULING DEFECT

**Previous results (PF 4.34, USD 48,010 equity) were artifacts of the exit-scheduling
defect where March 2019 signals exited in 2026.**

**Corrected results:**
- TEST fold: 284 opportunities, 69 accepted, 215 rejected
- Bankrupt: True (2020-07-01)
- PF: 0.88 (below 1.0 threshold)
- Ending equity: USD 0.00
- No 2026 exits in TEST fold

**Root cause:** `_generate_signal_opportunities()` fell back to global dataset end
(2026-07-22) when no next rebalance existed within the fold.

**Fix:** Added fold-aware opportunity generation with `unresolved` flagging,
fold boundary filtering on entry/exit, and `end_of_fold` rejection reason.

### Cost Stress

| Cost Level | Ending Equity | PF | Bankrupt |
|-----------|---------------|-----|----------|
| 3.0 bps | USD 0.00 | 0.098 | True |
| 5.0 bps | USD 0.00 | 0.098 | True |
| 8.0 bps | USD 0.00 | 0.098 | True |
| 12.0 bps | USD 0.00 | 0.098 | True |
| 0.0 bps (non-canonical) | USD 0.00 | 0.098 | True |
| Best trade removed | USD 0.00 | 0.048 | True |
| Best 3 trades removed | USD 0.00 | 0.000 | True |

### Period/Concentration Analysis

**Periods:**
- 2019-2020: 0 trades, USD 0.00
- 2021-2022: 0 trades, USD 0.00
- 2023-2024: 0 trades, USD 0.00

**Pairs:**
- EURUSD: 2 trades, USD -2,822.51
- GBPUSD: 2 trades, USD -1,719.99
- USDJPY: 2 trades, USD -1,067.12
- AUDUSD: 3 trades, USD -29,174.90

**Directions:**
- Long: 4 trades, USD -30,388.95
- Short: 5 trades, USD -4,395.56

## Test Results

**47 tests, all passing:**

### STSM Signal Tests (25 tests)
1. test_exact_skip_month_formula
2. test_current_close_not_endpoint
3. test_zero_threshold_sign_logic
4. test_no_lookahead
5. test_deterministic_rebalance_dates
6. test_canonical_pair_enforcement
7. test_usdchf_exclusion
8. test_native_mt5_d1_enforcement
9. test_dataset_fingerprint_enforcement
10. test_fold_isolation
11. test_no_test_leakage
12. test_signal_executable_ledger_separation
13. test_bankruptcy_cutoff
14. test_deterministic_trade_ids
15. test_accounting_v2_metadata
16. test_combined_pf_from_gross
17. test_costs_applied
18. test_no_order_imports
19. test_no_order_calls
20. test_paper_only
21. test_allow_live_orders_false
22. test_mt5_data_load
23. test_strategy_output_values
24. test_frozen_parameters
25. test_friday_signal_enters_on_next_available_bar

### Portfolio Accounting Tests (22 tests)
1. test_lifecycle_entry_and_exit
2. test_long_pnl
3. test_short_pnl
4. test_costs_charged_twice
5. test_fixed_notional
6. test_no_compounding
7. test_chronological_ordering
8. test_simultaneous_signal_ordering
9. test_ledger_reconciliation
10. test_fold_isolation
11. test_bankruptcy_cutoff
12. test_no_post_bankruptcy_acceptance
13. test_combined_pf_calculation
14. test_deterministic_audit_output
15. test_diagnostic_period_excluded_from_gates
16. test_no_order_imports
17. test_no_order_calls
18. test_accounting_metadata
19. test_cost_stress
20. test_period_concentration
21. test_ohlc_data_loading
22. test_signal_opportunity_generation

## Known Limitations

1. Full-history portfolio goes bankrupt in 2011 (AUDUSD losses exceed USD 10,000 equity)
2. TEST fold shows positive results but with high drawdown (84.5%)
3. No trades in 2019-2024 period buckets (trades concentrated in earlier years)
4. Profitability depends heavily on few trades (robustness score low)
5. USD 100,000 notional is hypothetical research exposure, not a recommendation

## Safety Compliance

- ✅ paper_only=true
- ✅ ALLOW_LIVE_ORDERS=false
- ✅ No watcher activation
- ✅ No signal forcing
- ✅ No order endpoint called
- ✅ No order placed
- ✅ Currency-strength remains closed
- ✅ Reporting system untouched
- ✅ Frozen preregistration unchanged