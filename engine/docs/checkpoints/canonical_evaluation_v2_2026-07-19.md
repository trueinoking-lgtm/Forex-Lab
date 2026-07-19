# Canonical Evaluation V2 — 2026-07-19

## Decision

**REJECTED.** EMA crossover is not called profitable. It has 20 completed lifecycle
trades (well below the 100-trade decision sample), and canonical profit factor is 1.1862,
below the locked 1.3 gate. It also fails every standard 3/5/8/12 bps friction scenario on
the PF gate and does not establish broad regime robustness. Observation may continue;
thresholds must not be lowered.

## Frozen evaluation and root cause

See `engine/results/reconciliation_EURUSD=X.md`. The frozen CSV has 777 bars from
2023-07-20 through 2026-07-17. The old result counted 30 position changes across repeated
walk-forward folds and computed PF from change-bar returns. The canonical ledger finds 20
closed lifecycles and one open-at-end position; PF becomes 1.1862. Walk-forward return
(6.4815%) and robustness (0.490) remain historical diagnostics, not proof.

## History and fragility

The requested 2015 start was unavailable from the reproducible local cache. No sources
were mixed: coverage is 2023-07-20..2026-07-17. Period returns for all five registered
strategies and four controls, plus the documented high/low-volatility and trending/ranging
breakdowns, are in `extended_baseline_EURUSD=X.json`. EMA selected-bar arithmetic returns
are 7.10% high-vol, 1.93% low-vol, 2.79% trending, and 8.35% ranging.

At 3/5/8/12 bps total friction, EMA PF is 1.186/1.159/1.121/1.073. Nonzero commission,
doubled spread/slippage, an extra bar of delay, neighboring parameters, best-trade removal,
best-three removal, best-year exclusion, long-only, short-only, and 50% exposure are recorded
for fragility only. Parameter neighbors were not optimized.

## Prospective holdout policy

Freeze SHA-256 of strategy source and canonical evaluation source, the EMA(12,26) parameter
hash, locked gates (score >=40, robustness >=0.3, walk-forward test return >0, PF >=1.3),
cost scenarios, and the 2026-07-17T00:00:00Z data cutoff. Starting with the next fully closed
candle, `src.forward_validation.append_entry` records a prediction made before next-bar
execution, version, timestamps, later outcome, costs, and gate state. This ledger is
append-only. All current data is a historically inspected period and can never be relabelled
an untouched holdout.

## Data integrity and reproducibility

Freshness now uses the newest fully closed candle plus expected interval, never the oldest
CSV row. Timestamps normalize to UTC; duplicates, sorting, gaps, incomplete last candles,
and fingerprints are manifested atomically. Network failure fails closed unless a valid
fresh cache exists.

From `engine/`:

```text
python run_canonical_v2.py
python run_canonical_v2.py  # byte-identical artifacts
python -m pytest tests/test_canonical_eval.py tests/test_trade_ledger.py tests/test_data_integrity.py tests/test_experiment_registry.py tests/test_tradeability_watcher.py -q
cd .. && python -m pytest engine/tests/ -q
```

No bridge source, filling mode, zero-spread policy, retcode logic, cron, signal timestamp,
or order endpoint was changed. Research remains paper/demo only.
