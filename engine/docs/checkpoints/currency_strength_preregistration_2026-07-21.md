# Currency-Strength / Relative-Value Research — Preregistration (Phase 1)

**Date:** 2026-07-21
**Status:** PRE-REGISTERED — design frozen BEFORE evaluating results.
**Accounting model:** `normalized_equal_risk_v1`
**Accounting version:** `2`
**Capital-allocation model:** normalized_equal_risk (explicit stop present) / fixed_notional_fixed_exposure (no stop)
**Safety:** RESEARCH ONLY — `paper_only=true`, `ALLOW_LIVE_ORDERS=false`, no order endpoints, no orders, no watcher activation, no signal forcing, no gate changes, forward-validation ledger untouched.

> This milestone is structurally different from the rejected families:
> single-pair EMA strategies, trend-continuation, range mean-reversion, session-breakout.
> It is a cross-sectional, multi-pair relative-value design built on currency strength.

## Hypothesis

Cross-sectional currency strength, derived from signed pair returns across a small
multi-pair universe, contains a reproducible, cost-surviving trading edge. The
primary bet: take the available pair whose base/quote strength differential is
largest (strongest currency vs weakest currency), in the direction implied by the
differential. This is a *relative-value* (cross-sectional) hypothesis, not a
single-instrument trend or reversion bet.

## Pair universe (limited-universe Phase 1)

MT5 H1 datasets, immutable fingerprints (do NOT substitute yfinance):

| Pair    | Source                 | Timeframe | Fingerprint |
| ------- | ---------------------- | --------- | ----------- |
| EURUSD  | MetaTrader5 demo history | H1        | `80cc20e9de10f929619902d618a32035f45d557751153d16484de46d8d5fcfc1` |
| GBPUSD  | MetaTrader5 demo history | H1        | `99a2564ae0040d6c47ec20d1ce84c82a464be44dafac05898ea7e2e53d1fa789` |
| USDJPY  | MetaTrader5 demo history | H1        | `3aad2f78b5b06f39ac7804d33845c40e31d2d00073937e2df8eb51512802db60` |
| AUDUSD  | MetaTrader5 demo history | H1        | `776a10f7326ba04bf68a7c95011aedeebee693b0c5eb22d2ea22a98332bb94a7` |

Currencies represented: EUR, GBP, USD, JPY, AUD.
The universe is INCOMPLETE for a full currency matrix (only pairs sharing USD/EUR/GBP/AUD/JPY
with USD as the hub). This is explicitly a **limited-universe Phase 1 study**. Missing crosses
(e.g. EURGBP, EURJPY, AUDJPY, GBPJPY) are NOT fabricated.

## Timeframe

H1 (1-hour candles), MT5 demo history. No resampling to other timeframes in Phase 1.

## Currency-strength formula

At every evaluation timestamp `t`, strength is computed using ONLY candles that have
fully closed at or before `t`. Base/quote sign convention:

- positive EURUSD return → strengthens EUR, weakens USD
- positive USDJPY return → strengthens USD, weakens JPY
- positive GBPUSD return → strengthens GBP, weakens USD
- positive AUDUSD return → strengthens AUD, weakens USD

Three ISOLATED subfamilies (kept separate; NOT combined into an opaque ensemble in Phase 1):

1. **equal-weight average signed return** — mean of signed returns across the pairs that
   contain the currency, weighted equally.
2. **volatility-normalized signed return** — signed return divided by rolling realized
   volatility of that pair's return, then averaged across containing pairs.
3. **ranked momentum score** — cross-sectional rank (0..1) of cumulative signed return
   across currencies, highest = strongest.

Lookbacks tested (H1 bars): **6, 12, 24, 48, 120**. Each lookback is evaluated as its own
configuration per subfamily.

## Signal construction

At each evaluation timestamp, compute per-currency strength for each subfamily/lookback.
Select the pair with the largest base-minus-quote strength differential among the four
available pairs. Direction: long the pair if base strength > quote strength, short if
quote strength > base strength.

Subfamilies tested separately:
- S1: strongest-vs-weakest continuation
- S2: strongest-vs-weakest + volatility filter (require pair realized vol below its
  trailing median)
- S3: strongest-vs-weakest + trend-confirmation filter (require pair return over the
  signal lookback to agree with the differential direction)

Mean reversion is explicitly NOT tested in this milestone.

## Rebalance / evaluation schedule

Evaluation on every closed H1 candle (every hour). Signal uses fully closed candles only.
Execution occurs no earlier than the next H1 candle open (no future information).

## Holding period

Fixed holding periods tested: **4h, 8h, 24h**. Plus event/rule exits below.

## Risk model

- one position per pair maximum;
- no contradictory simultaneous positions on the same pair;
- explicit portfolio exposure cap (max concurrent positions = **4**);
- explicit aggregate risk cap (sum of per-position risk <= cap, defined in risk units);
- ATR stop: **1.0 / 1.5 / 2.0 ATR** (ATR over signal lookback);
- optional target: **1.5R / 2R**;
- strength-rank reversal exit (close when the selected pair is no longer the
  largest-differential pair OR its differential sign flips);
- equity floor at zero; no trading after bankruptcy.

## Transaction costs

Baseline **3 bps** spread. Cost-stress grid (PART K) applies 5/8/12 bps, doubled spread,
doubled slippage, nonzero commission, one extra H1 execution delay.

## Parameter bounds (frozen)

- lookbacks ∈ {6,12,24,48,120}
- holding ∈ {4h,8h,24h}
- atr_stop ∈ {1.0,1.5,2.0}
- target ∈ {none,1.5R,2R}
- subfamily ∈ {equal_weight, vol_normalized, ranked_momentum}
- signal_filter ∈ {continuation, vol_filter, trend_confirm}
- max_concurrent = 4 (fixed)
- aggregate_risk_cap = fixed research value (e.g. 4% of equity per position, 12% aggregate)

## Fold boundaries (frozen, anchored/nested walk-forward)

Full H1 history spans ~2022-01-03 → 2026-07-17 (MT5 D1 anchor 2010-01-04 unavailable at H1).
Folds (anchored, no final-test leakage):

- DEV: 2022-01-03 → 2023-06-30
- VALIDATION: 2023-07-01 → 2024-12-31
- TEST (chronological): 2025-01-01 → 2026-07-17
- AGGREGATE CHRONOLOGICAL TEST = DEV+VALIDATION+TEST concatenated in time order
- FULL-HISTORY DIAGNOSTIC = entire span (diagnostic only, not for selection)

Parameter selection uses DEV/VALIDATION only. TEST and aggregate are never used for selection.

## Controls

- no-trade control
- random pair selection (multiple fixed seeds)
- random long/short direction (multiple fixed seeds)
- shuffled currency-strength ranks (multiple fixed seeds)
- equal-weight momentum across all available pairs
- individual pair momentum
- existing rejected families as historical references (EMA/trend-continuation/
  range-MR/session-breakout)

Randomized controls use multiple fixed seeds (>=10). Report median and 90th-percentile
randomized outcome and percentage of randomized runs beaten.

## Selection rule

Among S1/S2/S3 × lookbacks × holding × atr_stop × target that pass ALL acceptance gates
(PART L) on the chronological TEST fold (and aggregate), select the single configuration
with the highest score; tie-break by robustness then by completed-trade count. Selection
does NOT use full-history diagnostic.

## Rejection conditions

Reject the family if ANY of:
- aggregate chronological PF < 1.3
- aggregate chronological return <= 0
- robustness < 0.3
- score < 40
- < 300 completed aggregate trades
- < 40 completed trades on any traded pair
- positive in fewer than 3 of 4 pairs
- fails to survive 5 bps
- does not beat 90th-percentile randomized controls
- best trade > 15% of gross profit
- best three trades > 30% of gross profit
- any pair contributes > 50% of gross profit
- any single currency dominates the result
- nearby-parameter instability
- dependence on a single historical period

Also reject if apparent performance depends overwhelmingly on USD participation.

## Data cutoff

Latest MT5 H1 candle available at preregistration: 2026-07-17. No data beyond this used.

## Accounting version / capital-allocation

normalized_equal_risk_v1, version 2. Equal risk per position where a valid stop exists;
explicit fixed-exposure model where no stop exists. Shared equity, equity floor at zero,
account-currency-normalized PnL, pair-specific pip/tick conventions, explicit metric units.
No raw quote-price aggregation.

## Design-freeze statement

This document is frozen as of 2026-07-21. Parameter bounds, fold boundaries, controls,
selection rule, and rejection conditions MUST NOT be widened or retrofitted after viewing
test results. Any change constitutes a new preregistration.
