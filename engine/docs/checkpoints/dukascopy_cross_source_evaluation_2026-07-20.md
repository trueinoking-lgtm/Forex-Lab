# Dukascopy acquisition and cross-source checkpoint — 2026-07-20

## Decision

**4. NO STRATEGY DEVELOPMENT YET.** Dukascopy evidence is absent, yfinance daily OHLC is defective, and all five registered strategies are rejected on the extended MT5 history. No strategy is characterized as profitable.

## Dukascopy status

Automated public acquisition is **BLOCKED** on this VPS. The corrected request form is `GET https://freeserv.dukascopy.com/2.0/api/instrumentList?fields=id,name`; it returns HTTP 204 with no body. The previously assumed `api/historicalPrices` sub-path returns nginx HTTP 404. The public bi5/tick endpoints return a fixed 123,321-byte HTML error page and are discontinued or gated. No further endpoint guessing, private interface, credential, CAPTCHA bypass, or fabricated data was used.

`run_acquire_dukascopy.py` now appends the request `path` to the base URL instead of incorrectly sending it as a query parameter. Historical-price requests use the same builder. Bounded backoff, resumable chunks, atomic writes, manifests, fingerprints, incomplete-candle exclusion, and integrity checks remain intact. HTTP 204, nginx 404, and an empty 200 now produce a clear `Dukascopy public endpoint unavailable (HTTP ...)` operator status.

Smallest manual step: export EURUSD D1 bid candles for 2010-01-01 through 2026-07-17 from Dukascopy Historical Data Export in a normal interactive browser, save the unmodified file under `engine/data/`, record its SHA-256 and export settings, then rerun this checkpoint. Do not merge its candles with another provider.

## MT5 versus yfinance

The common range is 2010-01-04 through 2026-07-17. Inputs remained read-only.

| Measure | MT5 | yfinance |
|---|---:|---:|
| Rows / frame fingerprint | 4,297 / `5804551d9020...` | 4,306 / `a16c4dfe6207...` |
| File SHA-256 | `4c306902c878...` | `2d151e8429dd...` |
| Invalid OHLC | 0 | 118 |
| Source-only dates | 7 | 16 |
| Annualized close-return volatility | 8.2877% | 8.4442% |

Timestamp overlap is 4,290 candles. Absolute MT5/yfinance differences (median / p95 / maximum) are: open 0.000475 / 0.001993 / 0.015284; high 0.000164 / 0.002715 / 0.039550; low 0.000301 / 0.002791 / 0.547128; close 0.003192 / 0.012103 / 0.034026. The 0.547128 low outlier and 118 invalid yfinance envelopes reinforce the disclosed source defect.

Daily close-return directions agree on 2,192 of 4,289 comparable days (51.11%). EMA-crossover positions correlate 0.9339 and match exactly on 96.71% of overlap bars, but only 3 closed lifecycle trades have identical entry and exit dates (MT5 148, yfinance 146, union 291). These are session/provider differences, not permission to repair or merge data.

## Separate canonical evaluations

Identical `src.canonical_eval` parameters, lifecycle ledger, locked gates, and 3 bps total cost were applied independently. PF is lifecycle profit factor; return is walk-forward/OOS return. Every registered strategy is ineligible on both sources.

| Definition | MT5 closed / PF / return / score | yfinance closed / PF / return / score |
|---|---:|---:|
| EMA crossover | 148 / 1.0533 / -32.88% / 22.50 | 149 / 1.0541 / -36.01% / 22.04 |
| EMA trend pullback | 163 / 0.9138 / -5.90% / 28.41 | 171 / 1.0351 / -0.17% / 36.53 |
| RSI mean reversion | 265 / 0.8645 / -8.83% / 29.44 | 251 / 1.0146 / -1.11% / 42.89 |
| MACD trend confirmation | 367 / 0.8531 / -49.97% / 15.93 | 378 / 0.8633 / -59.08% / 16.24 |
| London breakout | 22 / 0.6624 / +1.35% / 37.13 | 22 / 0.6071 / +0.09% / 25.88 |
| No trade control | 0 / n/a / 0 / 0 | 0 / n/a / 0 / 0 |
| Buy-and-hold control | 0 / n/a / -15.47% / 0 | 0 / n/a / -19.54% / 0 |
| Simple-MA control | 94 / 1.0884 / -8.13% / 26.79 | 96 / 1.1068 / -1.36% / 33.61 |
| Momentum control | 420 / 0.9604 / -43.29% / 19.16 | 406 / 1.0393 / -43.57% / 20.60 |
| Fixed-shift control | 149 / 1.0464 / +50.73% / 66.90 | 150 / 1.1566 / +105.32% / 69.94 |

The fixed-shift randomized control fails the PF gate on both sources and is a chance-alignment diagnostic, not strategy evidence. Full completed/open counts, expectancy, drawdown, robustness, score, and every gate outcome are in `mt5_canonical.json` and `yfinance_canonical.json`.

EMA period results remain rejected in every period: MT5 PF is 0.7688 / 1.0587 / 0.8675 / 0.8892 and yfinance PF is 0.7549 / 1.0676 / 0.8885 / 0.8417 for 2010–2014 / 2015–2019 / 2020–2022 / 2023-present. Regime observations are MT5 2,139 high-vol, 2,138 low-vol, 1,795 trending, 1,594 ranging; yfinance 2,143 / 2,143 / 1,590 / 1,761. `period_regime.json` reports all ten definitions. EMA PF at 3/5/8/12 bps declines 1.0533/1.0295/0.9951/0.9516 on MT5 and 1.0541/1.0296/0.9943/0.9497 on yfinance; `cost_sensitivity.json` contains all definitions.

The requested MT5 V2-slice check found a real source distinction: the 2023-07-20..2026-07-17 MT5 slice has 778 rows, 20 closed plus one open and remains ineligible, but PF is 1.2270, so it does **not** reproduce the yfinance V2 PF 1.1862. The yfinance slice has 777 rows and reproduces V2 exactly. This mismatch is reported rather than forced.

Source policy: MT5 is the clean broker/session-aligned canonical research source; yfinance is comparison/breadth only because its OHLC is defective; a manual Dukascopy export would be independent validation. Evaluate sources separately and never merge candles.

## Safety and regeneration

Run `python engine/run_cross_source_v3.py` to regenerate the gitignored JSON artifacts. The script imports research evaluation and strategy code only. `paper_only: true`, `allow_live_orders: false`, locked gates, approval gates, execution code, cron, and signal timestamps are unchanged. No order endpoint was called and no order was placed.
