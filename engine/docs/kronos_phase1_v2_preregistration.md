# Kronos Phase 1 V2 — Preregistration

## Model Configuration
- Model: Kronos-mini (NeoQuasar/Kronos-mini)
- Tokenizer: Kronos-Tokenizer-2k (NeoQuasar/Kronos-Tokenizer-2k)
- Device: CPU

## Frozen Parameters
- lookback = 256 real D1 bars
- prediction_horizon = 5 real D1 bars
- origin_spacing = 5 D1 bars
- non-overlapping forecast windows
- T = 1.0
- top_p = 0.9
- sample_count = 1
- NumPy seed = 20260725
- PyTorch seed = 20260725

## Dataset
- Canonical source: raw_mt5_<PAIR>_1d.csv (MT5 D1 export)
- Frequency: D1 (calendar-day bars)
- Pairs: EURUSD, GBPUSD, USDJPY, AUDUSD
- Scoring: OHLC only
- Volume and amount: audit fields only, not scored

## Data Requirements
All four pairs must cover the largest common chronological period.
Expected common range: approximately 2010-01-04 through 2026-07-22.

### Required Manifest Fields (per pair)
- exact CSV path
- SHA-256 of CSV file
- row count (total)
- first timestamp (ISO 8601 UTC)
- last timestamp (ISO 8601 UTC)
- development boundaries (start, end, row_count within boundaries)
- validation boundaries (start, end, row_count within boundaries)
- sealed-test boundaries (start, end, row_count within boundaries)
- broker/server identity
- timezone semantics
- acquisition timestamp
- exporter version
- CSV SHA-256 re-verification token

### Fold Design
- Context bars may come from earlier splits
- All 256 input bars must precede the first target bar
- All 5 target bars must lie entirely inside the evaluated split
- No target bar may enter the input window
- Development data provides context for validation
- Development and validation data provide context for sealed test
- Target split determines the split label, not the source of context bars

### Origin Counts (expected, D1)
With N rows in a split and spacing=5, horizon=5:
origins = floor((N - 5) / 5) + 1

Expected approximate counts (D1, ~4300 total rows per pair):
- development (~3300 rows): ~659 origins
- validation (~400 rows): ~79 origins
- sealed-test (~400 rows): ~79 origins

## Evaluation Procedure
1. Run Kronos inference for each development origin (1 prediction per origin)
2. Score all 5 horizons independently against actual target bars
3. Write one distinct predicted OHLC row per horizon to the ledger
4. Run 5 frozen baselines (last value, random walk, drift, rolling mean 20, EMA 20)
5. Compute frozen metrics per pair, per split, per horizon, and aggregate
6. Apply advancement gates mechanically
7. Run validation split, then sealed test (once)
8. Replay aggregate from stored ledger

## Frozen Advancement Gates
- Zero leakage failures
- Deterministic replay passes
- OHLC validity rate ≥ 99.9%
- Aggregate normalized close MAE improvement ≥ 2% vs last value
- Improvement on ≥ 3 of 4 pairs
- Validation and sealed-test conclusions agree
- No single pair contributes > 50% of total improvement
- Directional accuracy not worse by > 1 percentage point
- Forecast failure threshold passes

## Prohibited
- Trading strategy construction
- Profit factor calculation
- Trading returns calculation
- Signal generation
- Entry rule optimization
- MT5 bridge modification
- Live orders
- Profitability claims

## Resource Reporting
- Total inference calls attempted
- Calls completed / failed / retries
- Wall-clock duration
- Average / median inference duration
- Peak RAM
- Disk consumed
- Forecast ledger size