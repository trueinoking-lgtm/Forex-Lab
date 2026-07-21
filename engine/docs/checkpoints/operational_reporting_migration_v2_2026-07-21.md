# Operational reporting migration v2 — 2026-07-21

## Every report job

- `aether-forex-daily` runs `app/scripts/daily_loop.mjs`, the canonical paper-research loop, and produces the SQLite-backed report payload.
- `trading-deliver-reports` now regenerates `app/scripts/report_payload.mjs`, prints `engine/results/daily_report_message.md` to stdout for the cron delivery contract, and archives that exact message under `engine/results/sent/`.
- `trading-run-daily` now runs `engine/.venv/bin/python run_backtest.py` from this repository. It no longer refreshes the standalone `/root/trading-agent` artifacts.
- `daily_loop` runs, in order: external idea imports and re-scoring; backtest; native strategy scoring; signal monitoring through normal gates; paper PnL update; outcome review; trend detection, ingestion, and review; optional rule updates; `report_daily.mjs`; and `report_payload.mjs`. None of the reporting steps places an order.

## Source policy

Watcher evaluation uses `source=yfinance`, `timeframe=1d`, and the configured 1095-day lookback. Long-history research artifacts state their own timeframe (currently `1d`) and are reported alongside the watcher policy. Every message prints a comparison line. A mismatch is printed explicitly as `source/timeframe differs: watcher=... vs research=...`; a match is printed as `source/timeframe differs: no; ...`.

Market regime, ADX, and close are advisory context only. They appear under “Advisory (market regime, not a signal)” and are separated from the rejected-family evidence table. Watcher eligibility is zero unless `watcher_last_result.json` explicitly has `tradeable=true`.

## Accounting policy

`PaperLedgerSnapshot` is schema v2 and records `ts`, `starting_equity`, `current_equity`, `realized_pnl`, `unrealized_pnl`, `open_risk`, `max_concurrent_risk`, `bankrupt`, `accounting_version`, `accounting_model`, `ledger_updated_at`, `ignored_legacy_records`, and `ignored_legacy_note`.

The paper account starts at USD 10,000. This is separate from the USD 100,000 research reporting notional and the two must not be combined. Paper trades have explicit stops, so the ledger uses `normalized_equal_risk_v1`, accounting version 2, with PnL in account-currency USD. Current equity is starting equity plus v2 realized and unrealized PnL. Bankruptcy is true at equity less than or equal to zero.

## Exact output changes

Previously, Telegram used the latest legacy `PnlSnapshot` and showed only equity and open risk. It also ranked strategies in language that could imply profitable or eligible status. The new message uses only the latest v2 `PaperLedgerSnapshot`, prints the full paper portfolio and accounting metadata, states watcher eligibility, reports every researched family as rejected, separates advisory context from evidence, and prints source/timeframe provenance.

`PnlSnapshot` previously contained `ts, account, open_risk, daily_pnl, equity`. It now also carries `accounting_version`; existing rows are backfilled to version 1 and new snapshots are version 2. The new `PaperLedgerSnapshot` is the canonical reporting ledger.

## Old-versus-new examples

Old:

```text
equity 10000.00 · open risk 0.0000
```

New:

```text
Paper portfolio (accounting-v2)
starting equity: 10000.00
current equity: 10000.00
realized PnL: 0.00
unrealized PnL: 0.00
open risk: 0.00
maximum concurrent risk: 0
bankrupt: false
accounting version: 2
last ledger update: 2026-07-21T00:00:00.000Z
ignored legacy records: 0
```

## Troubleshooting

If no ledger update exists, run `node scripts/db_migrate.mjs` and then `node scripts/paper_update_pnl.mjs` from `app/`. If watcher data is absent, malformed, unavailable, or not explicitly tradeable, the report correctly shows zero eligible. If research artifacts have another timeframe/source, inspect the explicit comparison line rather than treating advisory data as strategy evidence. Delivery failures should preserve the generated report because the script archives only after successful generation and output.

## Legacy-artifact behavior

Migration marks pre-v2 `PaperTrade` and `PnlSnapshot` rows as accounting version 1. They are excluded from realized PnL and current equity and are counted in `ignored_legacy_records`; the ledger note explains this exclusion. Cross-version comparison is a warning condition. Legacy `/root/trading-agent/reports_*.md` files are neither read nor delivered by the canonical cron.
