# Multi-Pair H1 Session Breakout — Phase 1 Preregistration

Date frozen: 2026-07-20  
Data cutoff: 2026-07-20  
Mode: research/paper/demo only (`paper_only=true`, `ALLOW_LIVE_ORDERS=false`)

This document is frozen before any session-breakout runner execution or performance computation. Phase 1 results will not be used to widen parameter bounds, redefine sessions, add indicators, redesign the strategy, or otherwise tune against final test folds. No sources will be merged.

## Hypotheses and variants

The primary, confirmatory hypothesis is that a fixed-UTC Asian-session range contains information exploitable during the London session: after a fully closed H1 candle breaks the range high or low by a preregistered buffer, enter in that direction at the next bar, with at most one directional entry per session. Exits are governed only by session close, ATR/range stop, target, and bounded holding rules below. Primary family selection uses **Asian range to London breakout only**.

Two secondary, explicitly exploratory variants are preregistered: Pre-London consolidation to London breakout, and London-range to New-York-overlap breakout. They cannot replace or redefine the primary based on its results.

Core pairs are EURUSD, GBPUSD, USDJPY, and AUDUSD. USDCAD is optional and may be included only if conforming H1 MT5 data are available before analysis.

## Fixed UTC sessions and DST policy

- Asian range: 00:00–07:00 UTC.
- London session / primary breakout window: 07:00–16:00 UTC.
- New York overlap: 12:00–16:00 UTC.
- New York session: 13:00–21:00 UTC.
- Secondary Pre-London consolidation window: 04:00–07:00 UTC, followed by 07:00–16:00 UTC London breakout.
- Secondary London range: 07:00–12:00 UTC, followed by 12:00–16:00 UTC New York-overlap breakout.

All boundaries are fixed in UTC. London, New York, and other daylight-saving transitions do **not** shift these UTC windows; only their wall-clock local equivalence shifts. DST regimes will be reported as diagnostics and cannot cause hindsight session redefinition.

## Frozen signal, execution, and exit rules

The Asian high/low uses completed H1 candles in the range window. A breakout requires the close of a fully completed candle beyond the corresponding boundary plus `breakout_buffer` in ATR units. Execution is at the next bar, preventing same-bar execution/look-ahead. At most one long and one short directional entry may occur per UTC session; reversals close an existing position before the opposite entry. Positions still open at a data cutoff are marked open-at-cutoff by the canonical ledger.

Frozen coarse parameter bounds are:

- `breakout_buffer`: {0, 0.05 ATR, 0.10 ATR}
- `min_range`: {none, 0.5 ATR, 0.75 ATR}
- `max_range`: {none, 1.5 ATR, 2.0 ATR}
- `stop`: {opposite side of range, 1.0 ATR, 1.5 ATR}
- `target`: {none, 1.0R, 1.5R, 2.0R}
- `max_holding`: {4 H1 bars, 8 H1 bars, session close}
- `atr_lookback`: {14}
- range and breakout windows: fixed as specified above
- direction permissions: long and short

One shared parameter set must be used across all pairs. A hierarchical rule is permissible only if completely chosen without final pair-level test results. Staged subfamily evaluation may reduce computation but may not widen these bounds.

Stops are evaluated as the opposite side of the range or 1.0/1.5 ATR from entry. Targets are absent or 1.0/1.5/2.0 initial-risk units. Forced exits occur after 4 or 8 completed H1 holding bars, or at the relevant session close (16:00 UTC for the primary), whichever preregistered rule applies.

## Costs

Standard total friction is 3 basis points round trip, including 1 bp commission. The remaining 2 bps represent spread and slippage, applied consistently in return accounting. Pair diagnostics will document the implied allocation (EURUSD 1 bp spread/slippage each; GBPUSD 1.25/0.75; USDJPY 1/1; AUDUSD 1.25/0.75), while total standard friction remains 3 bps for every pair. A 5 bps total-friction stress is mandatory.

## Chronological folds

Exact date boundaries are derived once from each pair's available, cutoff-constrained H1 coverage, before strategy outcomes are computed. Whole UTC dates are assigned chronologically at approximately 60/20/20 observations: DEV begins at the first complete eligible date and ends at the latest date containing no more than 60% of observations; VAL begins the next UTC date and ends at the latest date containing no more than 80%; TEST is every later observation through 2026-07-20. The runner persists the exact resulting start/end timestamps for each pair. No observations or dates are shuffled, and boundaries cannot be moved after performance is viewed. `aggregate_cross_pair_test` combines the four core pairs' chronological TEST trades (plus optional USDCAD only if admitted before analysis).

## Candidate selection and controls

Development and validation alone select the shared candidate. The final chronological test is evaluated once and is never used for tuning. Candidates must satisfy the four aggregate gates (positive return, profit factor at least 1.3, robustness at least 0.3, score at least 40); eligible candidates are ranked first by `robustness * sign(score)`, then by profit factor—not by maximum return or maximum profit factor. If none qualifies before TEST, the family is rejected without adapting it.

Controls are no-trade; random session direction using multiple deterministic seeds; random breakout time using multiple deterministic seeds; previous-day high/low breakout; the existing D1 London-breakout approximation; and buy-and-hold as a diagnostic only. Random controls must report their median and 90th-percentile outcomes.

## Acceptance and rejection

Acceptance requires every condition below on the aggregate chronological test unless a diagnostic scope is named:

- aggregate PF >= 1.3, aggregate return > 0, robustness >= 0.3, and score >= 40;
- at least 200 aggregate trades and at least 30 trades in each core pair;
- performance beats both the median and 90th percentile of randomized controls;
- no pair supplies more than 50% of aggregate gross profit;
- the best trade contributes no more than 15% and the best three trades no more than 30% of total net profit;
- remains acceptable/positive under 5 bps total friction;
- positive net performance in at least three of four core pairs;
- no material period dependence, nearby-parameter stability, and concentration of the edge in the intended session.

If any acceptance condition fails—or required real H1 MT5 data are absent—the Phase 1 classification is **REJECT STRATEGY FAMILY** (or **REJECT pending data** where no performance computation is possible). Missing data never authorizes synthetic/fallback results.

## Data and implementation identity

Only clean, per-pair MT5 H1 CSVs are admissible. No yfinance substitution, fabricated H1 history, or source merging is allowed. Synthetic fixtures may exist only under tests and are never research results.

Strategy code hash: `PLACEHOLDER — orchestrator must fill with the git hash of the committed engine/strategies/session_breakout.py after the strategy commit; no runner may use the placeholder for a final real-data report.`

Safety rails remain unchanged: research/paper/demo only; no live-order enablement, endpoints, calls, or orders; execution gates unchanged; watcher and forward ledger untouched; and no credentials.
