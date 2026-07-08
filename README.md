# Aether Forex Lab

Local-first **forex strategy research + paper-trading** dashboard. Built from a
spec that required: version one must **never place live trades**, must be
**paper-only**, must **never ask for or store broker secrets**, and must
**stop on real data errors** (no silent fake data).

## Architecture (hybrid: Python engine + Next.js/SQLite UI)
```
aether-forex-lab/
  engine/        # Python — validated quant engine (reused across the project)
    src/         # data, backtest, score, signals, risk, metrics, log(redact)
    strategies/  # registry: ema_crossover, ema_trend_pullback, rsi_mean_reversion,
                 #          macd_trend_confirmation, london_breakout
    run_backtest.py  # walk-forward backtest + scoring -> results/*.json
    run_signals.py   # daily paper signals, risk-gated, SL/TP mandatory
    tests/        # 18 pytest tests
  app/           # Next.js 14 (app router) + better-sqlite3
    app/          # 9 pages: Overview, Rankings, Strategy Profile, Signals,
                 #          Paper Trades, Decision Journal, Performance, Rules, Reports
    scripts/      # npm command implementations (db, score, monitor, pnl, ...)
    schema.sql    # SQLite schema (12 tables)
    scripts/*.test.mjs  # 5 TS safety tests
```

## Safety guarantees (verified by tests)
- `paper_only: true` + `allow_live_orders: false` in engine config; `run_signals.py`
  refuses to start if either is wrong.
- Engine has **no broker code** (`place_order`/`execute_trade`/`broker_password`
  asserted absent by tests). No live orders are possible by construction.
- Market-data failures **raise** (never fall back to fake data). Demo/seed data
  is flagged `is_demo=1` in the DB and labeled in the seed script.
- Optional API keys come only from `.env` (`YFINANCE_API_KEY`); they are
  **redacted** in all logs/UI via `src/log.py` and `scripts/db.mjs`.

## Setup (local)
```bash
# 1. Engine (Python)
cd engine
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run_backtest.py          # backtest + score on real EURUSD data

# 2. Dashboard (Node)
cd ../app
npm install
npm run db:migrate                        # create SQLite schema
npm run score:strategies                  # load scores into DB
npm run monitor:signals                   # generate + store paper signals
npm run dev                               # http://localhost:3000
```

## Commands
| command | what it does |
|---|---|
| `npm run dev` | start Next.js dashboard |
| `npm run db:migrate` | create SQLite schema (idempotent) |
| `npm run seed` | seed **demo** (labeled) candles + strategies + 1 rule |
| `npm run import:prices <csv> <pair> [--demo]` | CSV OHLCV import |
| `npm run backtest` | run walk-forward backtest + scoring (Python engine) |
| `npm run score:strategies` | load engine scores into SQLite |
| `npm run monitor:signals` | generate paper signals + decision journal + paper trades |
| `npm run paper:update-pnl` | snapshot account PnL, close trades on SL/TP |
| `npm run review:outcomes` | review open trades at 1h/4h/24h/final |
| `npm run update:rules <rule> <value> [reason]` | versioned rule change |
| `npm run report:daily` | build + store end-of-day report |
| `npm run report:payload` | build the Telegram-ready JSON + concise message |
| `npm run daily:run` | run the full safe scheduler loop (see below) |
| `npm run test` | run 8 TS safety tests (engine has its own pytest) |

Engine tests (separate): `cd engine && .venv/bin/python -m pytest tests/ -q`

## v1.1 — scheduler, locking, logging, Telegram delivery

### Daily scheduler (safe)
`npm run daily:run` orchestrates the full paper-research loop in order:
`backtest → score:strategies → monitor:signals → paper:update-pnl →
review:outcomes → (optional) update:rules → report:daily → report:payload`.

Safety properties (verified by tests):
- **No overlapping runs**: a `SchedulerLock` row (id=1) is held for the whole run
  and released at the end. A second run refuses with `Refusing overlapping run`.
- **Fail loud**: any non-zero step aborts the whole run, logs the error, and
  records an overall `success=0` row. Engine data/API failures are never hidden
  or faked — the yfinance load raises, so a bad market-data day stops the loop.
- **Never live**: the engine enforces `paper_only: true` + `allow_live_orders: false`;
  the loop only runs read/scoring/report commands.
- **Every run is logged**: `SchedulerRunLog` records `started_at`, `finished_at`,
  `command`, `success`, `error_message`, and an `output_summary` per step.

### Telegram delivery (report:daily only, minimal)
The project stays **token-free**: a Hermes cron (`aether-forex-daily`) runs the
loop and delivers the concise daily message to the **#reports** topic only.
`scripts/telegram_deliver.mjs` prints just the message (or a short failure note)
to stdout; Hermes delivers that stdout. The message contains only: daily paper
PnL, best/worst strategy, best/worst paper trade, rule changes (last 24h),
whether regime-filtered signals beat buy-and-hold, and any warnings/errors.

### Enabling / disabling the scheduler
- **Hermes cron** `aether-forex-daily` (job id `c5838006d19e`), schedule `0 22 * * *`
  (22:00 UTC). Pause: `cronjob action=pause job_id=c5838006d19e`.
  Resume: `cronjob action=resume job_id=c5838006d19e`.
- Manual run any time: `npm run daily:run` (refuses to overlap a running cron).
- Clear a stale lock after a crash: `DELETE FROM SchedulerLock WHERE id=1;`.

### Next.js version
Pinned to **14.2.35** (latest patched 14.2.x). We stay on the 14.2 line: Next 15+
requires React 19 and changes App Router caching/defaults — a breaking-major jump
not needed for this local dashboard. Revisit when a feature needs 15+.

## What uses demo data
- `npm run seed` inserts clearly-labeled `is_demo=1` candles — **synthetic, not real**.
- The default research flow uses **real EURUSD data via yfinance** (no key).

## What needs real market data
- Backtests, signals, and paper PnL all read real OHLCV. yfinance works key-less
  for daily FX. For intraday or live feeds, add an adapter later — keep keys in `.env`.

## Still needs manual setup
- A real broker adapter for **live** trading is **out of scope** (v1.1 is paper-only).
- Intraday data + true session-time reviews (London breakout adapted to daily in v1).

## Honest results from the first real run (EURUSD, 2023-07..2026-07, 3y)
Best OOS score: `ema_crossover` (41.9). Over this window, buy-and-hold still
beat every active strategy — the harness correctly reports that, rather than
overstating edge. The scoring + robustness penalty is doing its job: strategies
that only win in one lucky window are down-weighted.

---

## v1.2 — Multi-Market Research Hub

Aether Forex Lab is now a **multi-market research hub**: forex majors + gold
research mode live, crypto research mode present-but-disabled until enabled.

### Market universe + metadata
Every market carries structured metadata so the engine applies the right cost
model, session filter and data source:

| field | meaning |
|---|---|
| `asset_class` | forex / metal / crypto / index / equity |
| `symbol` | instrument (EURUSD, XAUUSD, BTCUSD…) |
| `session` | fx_major / london / ny / 24h / commodity |
| `spread_model` | fixed_bps / variable / commission |
| `volatility_profile` | low / medium / high / extreme |
| `data_source` | yfinance ticker or `csv` |

Run `npm run seed:markets` to populate the `Market` table. Crypto (BTCUSD,
ETHUSD) is seeded with `enabled=0` — research-later.

### External research imports (idea sources only)
Three adapters normalize external results into one shape, **validate**
(fail-loud on fake/implausible numbers), **label `is_external=1`**, then
**re-score with OUR spread, slippage, walk-forward and paper rules** before
they can enter the lab:

- `tradingview` — TradingView / PineScript strategy reports
- `traderdev` — trader.dev / MCP backtest result import (if available)
- `generic` — generic backtest result via JSON/CSV

```bash
npm run import:external ../engine/data/sample_imports_tradingview.json
npm run import:external ../engine/data/sample_imports_traderdev.json
npm run import:external ../engine/data/sample_imports_generic.csv
```

**Source-of-truth contract:** the external headline return is NEVER trusted
as-is. `engine/src/imports.py::re_score()` charges the gap between the
external cost model and OUR per-asset-class default (override wins), so an
imported strategy can only rank if it survives our costs and robustness.

### Pages added
- `/markets` — universe + filter by asset class
- `/market-profile?symbol=XAUUSD` — per-market metadata + researched strategies
- `/imports` — re-scored external strategies (ext. return → our re-score)
- `/cross-market` — top strategies per asset class, native + external side by side

### Safety (unchanged)
Paper-only by default. No live execution. No broker credentials. No private
keys. External platforms are idea sources only; this lab is the source of truth.

### Tests
- Engine (`pytest`): market universe, import validation, external labeling,
  re-scoring cost-model override, no-live-execution guarantee (39 pass).
- App (`npm test`): schema tables, crypto-disabled seed, import loader has no
  order/execute/broker code, re-score source-of-truth, labeling (14 pass).
