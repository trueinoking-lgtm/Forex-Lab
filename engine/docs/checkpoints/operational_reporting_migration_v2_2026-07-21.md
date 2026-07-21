# Operational reporting migration v2 — 2026-07-21

## Every report job

- `aether-forex-daily` runs `app/scripts/daily_loop.mjs`, the canonical paper-research loop, and produces the SQLite-backed report payload.
- `trading-deliver-reports` now regenerates `app/scripts/report_payload.mjs`, prints `engine/results/daily_report_message.md` to stdout for the cron delivery contract, and archives that exact message under `engine/results/sent/`.
- `trading-run-daily` now runs `engine/.venv/bin/python run_backtest.py` from this repository. It no longer refreshes the standalone `/root/trading-agent` artifacts.
- `daily_loop` runs, in order: external idea imports and re-scoring; backtest; native strategy scoring; signal monitoring through normal gates; paper PnL update; outcome review; trend detection, ingestion, and review; optional rule updates; `report_daily.mjs`; and `report_payload.mjs`. None of the reporting steps places an order.

## Source policy

The report distinguishes TWO sources that must never be conflated:

- **Advisory / watcher source** = `short_window_yfinance_advisory`: `yfinance`,
  `EURUSD=X`, `1d`, rolling 1095-day window (from `engine/config.yaml`). This is a
  short-window advisory signal context only. It is NEVER labelled canonical research
  and NEVER determines long-history research conclusions.
- **Canonical long-history research source** = `MT5 EURUSD D1`, coverage
  `2010-01-04` → `2026-07-17`, dataset fingerprint
  `4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2` (from
  `engine/results/range_mr_period_regime.json`). Read from the MT5 demo-history
  manifest. Intraday research uses the four verified MT5 H1 datasets
  (`raw_mt5_{EURUSD,AUDUSD,GBPUSD,USDJPY}_1h.csv`).

Because the providers, timeframes, coverage windows, and fingerprints differ, the
report prints **`Sources differ: YES`**. The canonical fingerprint is asserted at
report time; a missing or mismatched fingerprint fails the run loudly.

Market regime, ADX, and close are advisory context only. They appear under
“Advisory (market regime, not a signal)” and are separated from the rejected-family
evidence table. Watcher eligibility is zero unless `watcher_last_result.json`
explicitly has `tradeable=true`, and is a separate axis from canonical-research
classification.

## Operational script versioning

The Hermes cron scripts (`/root/.hermes/scripts/trading_deliver_reports.sh`,
`trading_run.sh`) are GENERATED operational files. The **authoritative** copies live
in the repository under `ops/hermes/`. `scripts/install_hermes_forex_reporting_jobs.sh`
backs up any existing external script, copies the repo version with executable
permissions, verifies SHA-256 after install, refuses stale `/root/trading-agent`
references, supports `--verify` mode, and never prints secrets.

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
