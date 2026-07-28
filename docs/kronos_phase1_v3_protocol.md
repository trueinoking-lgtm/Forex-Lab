# Kronos Phase 1 V3 — Prospective Replication Protocol

**PROSPECTIVELY FROZEN REPLICATION INFORMED BY DISCLOSED EXPLORATORY PRIOR RESULTS**

## Research question

On genuinely post-freeze broker-native D1 targets for EURUSD, GBPUSD, USDJPY,
and AUDUSD, does frozen Kronos-mini have lower origin-close-normalized absolute
close error than one globally frozen development-selected deterministic
baseline?

This is a forecasting question. Directional advancement is a separate decision
for possible later trading-signal research. Neither result is a profitability,
strategy, or trading claim.

## Prior evidence disclosure

Run A is an exploratory pilot with an invalid evaluator. Its results were
viewed. It may inform implementation guards, shape validation, leakage tests,
replay, and evidence completeness, but not unbiased performance conclusions.
V2 gates were constructed after exploratory results and are not a valid
preregistration. Synthetic structural evidence also influenced the close-only
engineering policy.

## Freeze identity and prospective interval

| Field | Frozen rule |
|---|---|
| `protocol_freeze_commit` | `SELF`: resolve to the commit containing this protocol |
| `protocol_freeze_timestamp` | `COMMITTER_TIMESTAMP` of that commit |
| `external_timestamp_reference` | Git commit object; an approved remote push receipt or immutable hash-chained freeze entry may strengthen it before acquisition |
| `first_authorised_test_target` | first complete broker-native D1 target bar strictly after the freeze timestamp |
| `last_authorised_test_target` | target bar completing the 100th non-overlapping five-bar origin on the verified four-pair common calendar |

The interval is unresolved until approved source bars exist. A calendar date
must not be guessed. The first target must be strictly later than the freeze
timestamp and may never move backward.

## Frozen model and forecast design

- Model: `NeoQuasar/Kronos-mini`, revision
  `f4e68697d9d5aed55cef5c96aabc3376bcad9f81`.
- Tokenizer: `NeoQuasar/Kronos-Tokenizer-2k`, revision
  `26966d0035065a0cae0ebad7af8ece35bc1fb51c`.
- Engineering integration: `76f46719d17b79c541136d8d4ade42ea6205413e`.
- CPU, evaluation mode; context 256; horizon 5; origin spacing 5.
- Seed `20260725`; temperature `1.0`; top-p `0.9`; sample count `1`.
- Raw close is the primary forecast. Raw OHLC validity is diagnostic only.
- No projection may be used in primary scoring.

## Data and acquisition

The source is direct MT5 broker-native D1 export from `MetaQuotes Ltd.` /
`MetaQuotes-Demo`, with exact symbol mappings EURUSD→EURUSD, GBPUSD→GBPUSD,
USDJPY→USDJPY, and AUDUSD→AUDUSD. A source or mapping change invalidates the
study. Exact timestamp semantics, close rule, delay, serialization, immutable
batching, quality rules, and hash chaining are in the acquisition policy.

Historical development/validation data and prospective final-test data use
separate storage roots. Prospective batches may be archived after freeze but
must not be opened by development or validation, summarized, scored, or used
for any inference until final-test authorisation.

## Development, validation, and final test

1. Development is historical and exploratory. It may select one global point
   baseline from the four frozen deterministic candidates. No protocol, model,
   code, metric, threshold, fold, origin, cleaning, or aggregation change is
   permitted afterward.
2. Validation uses the frozen winner and pipeline. It may only decide advance
   or stop. It cannot reselect a baseline.
3. The final test runs once after 100 complete non-overlapping origins per pair
   accrue and all identities are authorised. It cannot reselect a baseline or
   alter any method.

Any post-freeze semantic change invalidates the study. A documented,
non-result-driven technical invalidation preserves all partial evidence and
requires complete restart under a new study identity and later unexposed
targets. Poor performance, failed gates, or surprising output are completed
results, never technical invalidations.

## Decision reporting

- **A. Forecast superiority passed; directional advancement passed**
- **B. Forecast superiority passed; directional advancement failed**
- **C. Forecast superiority failed**

The directional outcome never rewrites the primary forecasting outcome.

## Final-test counter design

The counter is append-only, hash-chained, and inactive. Before model loading it
must atomically append attempt 1 and refuse if an attempt already exists.
Required fields are study ID, freeze commit, authorised interval, attempt,
start, status, code/config/model/tokenizer/dataset/fold/origin/evidence hashes,
previous/current record hashes, and any technical-invalidation reason plus
approval reference.
