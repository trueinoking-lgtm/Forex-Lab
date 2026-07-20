> **SUPERSEDED — accounting only (2026-07-20).** Preserve all original metrics and classification below as historical record. PF, expectancy, gross PnL, and concentration used `legacy_raw_price_units_v1` (version 1). Every corrected registered-strategy result is classified **rejected** under `normalized_equal_risk_v1` (version 2); see [Canonical accounting migration](canonical_accounting_migration_2026-07-20.md).

# Historical Data Expansion & Canonical Rebaseline V3 — 2026-07-19

## Decision

**NO STRATEGY DEVELOPMENT YET.** The required extended history was not obtainable on this VPS: the approved yfinance request failed at DNS resolution, and no logged-in MetaQuotes demo terminal or second valid source was available. The real canonical cache covers only 2023-07-20 through 2026-07-17 (777 D1 bars). It is insufficient evidence for persistence across multiple periods and regimes. No data was fabricated.

## Root cause and acquisition

The old history limit is a request-parameter cap, not a provider limitation. `config.yaml` fixes `data.lookback_days` at 1095; `src/data.py::fetch_yfinance` formerly requested `now-(lookback_days+30)` and then filtered to `now-lookback_days`, producing about three years. V3 accepts an explicit `start`/`end` override. Regenerate with:

```bash
cd engine
.venv/bin/python run_acquire_data.py --start 2010-01-01
```

The command requests yfinance `EURUSD=X`, interval `1d`, normalizes UTC, excludes the current incomplete daily candle, atomically writes CSV and manifest, and records file and frame SHA-256. If Yahoo cannot provide the range, `mt5_history_export.py` is a separate read-only PC fallback. It imports no execution modules, exposes no account identifier, and records only sanitized company/server metadata. Its parser is tested without MetaTrader5; live export still requires an online logged-in demo terminal.

## Canonical policy and integrity

yfinance is canonical when its requested coverage and integrity checks pass. Each provider remains a separate raw dataset; sources are never merged. A future MT5 overlap must compare timestamps, exact OHLC matches, median/max price differences, missing candles, weekends, rollover boundaries and volume compatibility. Broker daily rollover differences are session-boundary differences, not automatically corruption. No overlap comparison was possible because only one valid dataset exists.

The preserved V2 cache is immutable for this run: 777 sorted, unique, finite, positive UTC bars; no weekend bars or >5% close discontinuities; one >4-calendar-day forex-aware gap. Strict OHLC envelope validation flags 26 adjusted provider rows where adjusted open/close lies slightly outside adjusted high/low. They remain disclosed and unchanged because silently repairing them would break exact V2 reconciliation. Canonical file SHA-256: `1382b3eca73349f76de0a97848c915d86f8e8e04cc65a5d494941edf52cac507`.

## Canonical comparison

All eligibility paths call `src.canonical_eval`; closed/open lifecycle counts are shown below. Gates remain score >=40, robustness >=0.3, walk-forward return >0 and lifecycle PF >=1.3.

| Path | Closed/open | Wins/losses | PF | OOS return | DD | Robustness | Score | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| EMA crossover | 20/1 | 5/15 | 1.1862 | 6.48% | -9.33% | .490 | 46.08 | No |
| EMA trend pullback | 32/1 | 12/20 | .6669 | -.35% | -3.28% | .206 | 25.01 | No |
| RSI mean reversion | 51/0 | 36/15 | 3.3161 | .97% | -2.93% | .000 | 64.82 | No |
| MACD trend confirmation | 79/1 | 32/47 | .7740 | -12.63% | -17.60% | .206 | 13.52 | No |
| London breakout | 8/0 | 1/7 | .3274 | -1.64% | -1.64% | .029 | 16.96 | No |
| No trade | 0/0 | 0/0 | n/a | 0 | 0 | 0 | 0 | No |
| Permanent long | 0/1 | 0/0 | n/a | 2.06% | -8.63% | 0 | 0 | No |
| Simple MA crossover | 16/1 | 2/14 | .8460 | 10.16% | -6.82% | .588 | 47.25 | No |
| Fixed-period momentum | 58/1 | 22/36 | 1.6759 | 1.08% | -9.80% | .529 | 46.94 | Yes |
| Fixed-seed randomized entry | 21/1 | 9/12 | 1.6779 | 24.64% | -6.32% | .647 | 75.65 | Yes |

The eligible controls are sanity comparators, not authorization evidence; the randomized result particularly warns that this short sample can reward chance alignment. Full expectancy, holding time, exposure, concentration, loss streak and side splits are in the JSON.

Only 2023-present has coverage (777 bars); 2010-2014, 2015-2019 and 2020-2022 are explicitly insufficient. No complete rolling 3y/5y window exists. Regime observations are 379 high-vol, 378 low-vol, 296 trending and 298 ranging bars. Regime classification uses `signals.classify_regime(high, low, close)`: Wilder ADX(14), trend >25, range <20, otherwise unknown; volatility is 20-day return standard deviation split at the full-sample median. Parameters were fixed.

At 3/5/8/12 bps total friction EMA PF declines 1.1862/1.1595/1.1211/1.0728 and remains rejected; OOS return declines 6.48%/5.57%/4.22%/2.44%. Simple-MA PF declines .8460/.8293/.8053/.7751 and remains rejected; return declines 10.16%/9.35%/8.14%/6.55%. Nonzero 1-bp commission, doubled spread/slippage and one extra execution-bar delay are separately reported; no optimization was performed.

The exact 2023-07-20..2026-07-17 slice reproduces V2: EMA PF 1.186232434520887, 20 closed plus one open, OOS return 0.06481509154533205, eligible false. Legacy position-change PF 1.55 remains invalid and is not used.

## Research protocol if data becomes available

Minimum decision sample: 100 closed lifecycles overall, at least 20 in each evaluation period and material representation in trend/range and high/low-vol regimes. Freeze a chronological development segment, then one untouched evaluation segment; use anchored walk-forward folds and one final holdout. Initial bounds for a future research proposal only: EMA/trend fast 8–30, slow 40–150, pullback lookback 10–40 and standardized pullback 0.5–2.0. Reject if any locked gate fails on holdout, PF <1.3, return <=0, robustness <.3, score <40, fewer than 100 lifecycles, best trade >25% or best three >50% of gross profit, either side is materially loss-making without a predeclared side restriction, or results fail multiple periods/regimes and cost/delay stress. Use nested/blocked validation, a small preregistered grid, multiplicity disclosure, no period-specific tuning, and no source mixing.

## Safety and rerun

This milestone is research/paper/demo only. `paper_only: true` and `allow_live_orders: false` remain unchanged. No watcher, cron, bridge authentication, order endpoint, filling policy, zero-spread rule or retcode mapping changed. Neither exporter imports execution code nor calls an order API. No order endpoint was invoked and no order was placed. Bridge state: offline/unavailable; export pending an online demo terminal.

Artifacts under `engine/results/` are gitignored and deterministic. Run focused and full tests with `.venv/bin/python -m pytest tests/ -q`; rerun V3 with `.venv/bin/python run_historical_rebaseline_v3.py`, then compare JSON and fingerprints.
