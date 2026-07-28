# Kronos Phase 1 V3 — Status

## Required classifications

Run A:

**EXPLORATORY PILOT — INVALID EVALUATOR — RESULTS WERE VIEWED**

V2 gates:

**POST-RESULT EXPLORATORY GATES — NOT A VALID PREREGISTRATION**

V3:

**PROSPECTIVELY FROZEN REPLICATION INFORMED BY DISCLOSED EXPLORATORY PRIOR RESULTS**

Engineering integration commit:

`76f46719d17b79c541136d8d4ade42ea6205413e`

The integration commit is engineering evidence only, not performance evidence.

## Current authorisation

- Protocol and provenance-test creation: authorised.
- Real Forex inference: not authorised.
- Development, validation, and final-test execution: not authorised.
- Data acquisition: not activated by this commit.
- Final-test execution counter: designed, not activated.
- Safety: `paper_only=true`, `ALLOW_LIVE_ORDERS=false`; no orders, watcher
  activation, signal forcing, or gate lowering.

The current repository has no verified V3 real-source dataset, final fold
manifest, final origin manifest, authorised test interval, or active execution
counter. Those objects must not be invented.

## Prospective-start rule

`protocol_freeze_commit: SELF` means the Git commit containing this protocol.
`protocol_freeze_timestamp: COMMITTER_TIMESTAMP` means that commit object's
immutable committer timestamp. Before acquisition, an approved remote push
receipt or immutable hash-chained freeze record may strengthen the external
timestamp reference without changing any protocol semantics.

The first authorised final-test target is the first complete broker-native D1
bar strictly after that timestamp. It must satisfy:

`first_authorised_test_target > protocol_freeze_timestamp`

The start may move forward to accommodate completeness or acquisition delay. It
may never move backward.
