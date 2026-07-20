# Portfolio accounting audit — 2026-07-20

## Decision

**1 REJECT STRATEGY FAMILY.** The exact frozen Phase 1 candidate and folds were
rerun without reselection. Corrected accounting fails return > 0, PF >= 1.3,
robustness >= 0.3, score >= 40, three-positive-pair breadth, and 5 bps survival.

## Root cause and canonical units

The old ledger mixed quote-price movement (`exit-entry`) with entry-normalized
returns. This made a move in USDJPY near 150 roughly 100 times larger in PF and
expectancy than a comparable percentage move in a pair near 1. The canonical
closed-trade formula is now:

`net USD PnL = direction × ((exit-entry)/entry) × USD 100,000 − total_bps/10,000 × USD 100,000`.

The shared research account starts at USD 100,000. Each lifecycle trade is
evaluated on the same USD 100,000 notional; this is a normalization convention,
not broker tick metadata or a claim of four-times capital leverage. Arithmetic
portfolio return is `sum(net USD PnL) / USD 100,000`. PF, expectancy, return,
ending equity, and drawdown use the identical 857 closed trade IDs and net-PnL
field. Aggregate PF is combined gross profit divided by combined gross loss,
never a mean of pair PFs.

## Before / after reconciliation

| metric | before (mixed units) | after (canonical USD) |
|---|---:|---:|
| closed trades | 857 | 857 |
| gross profit | 12.842505 raw price units | USD 67,094.158655 |
| gross loss | 9.695790 raw price units | USD 94,693.422245 |
| profit factor | 1.3245445 | 0.7085409 |
| expectancy | 0.00367178 raw price units/trade | USD -32.204508/trade |
| arithmetic return | -27.59926% | -27.59926% |
| ending equity | not consistently defined | USD 72,400.736410 |
| max drawdown | -27.58% | -31.58434% |
| robustness / score | 0.000 / 24.60 | 0.000 / 15.85 |
| USDJPY share of gross profit | 94.7771% | 12.1359% |

Pair net contributions after normalization are EURUSD USD -9,323.91, GBPUSD
USD -18,115.10, USDJPY USD +2,243.22, and AUDUSD USD -2,403.48. At 5 bps,
PF is 0.5739904 and return is -44.73926%.

## Equity floor and controls

The paper simulator caps any realized loss at available equity, sets equity to
zero and marks the account bankrupt, then accepts no later entries. It records
both uncapped and capped PnL for auditability. Exact-equity and gap-through
excessive-loss cases are covered by regression tests. Randomized controls now
carry explicit `BANKRUPT` or `SURVIVED` classifications; all 20 frozen controls
are classified bankrupt under the shared-equity diagnostic and cannot rescue
the rejected strategy.

The four H1 input SHA-256 fingerprints and D1 retry fingerprint were verified
unchanged. Strategy signals, sessions, parameters, folds, preregistration,
watcher, forward ledger, gates, and execution/order code were not changed.
