# Strategy research baseline — 2026-07-19

## Safety and reproducibility checkpoint

This milestone is research-only. No watcher wrapper was run, no order endpoint was called, and no order was placed. `paper_only: true`, `allow_live_orders: false`, all four approval gates, execution code, cron, and signal timestamps were left unchanged.

Repository HEAD is `dc3074ae15ef959ff2e80860ff7bbfdcf1fff09e`. The initial worktree was clean. Root crontab contains the exact `5,35 * * * * /root/aether-forex-lab/engine/scripts/run_watcher.sh` entry and the wrapper is mode `700`. The sandbox cannot access the host service manager, so cron daemon activity and a genuine scheduled execution could not be independently established; a manual run was deliberately not substituted. The bridge `/quote?symbol=EURUSD` probe failed closed before HTTP with DNS resolution failure (`curl` exit 6). The previously observed state supplied in the brief was HTTP 502.

The exact required command, `cd engine && python run_backtest.py --pair EURUSD=X`, was attempted but Yahoo refresh failed under restricted DNS. The cache loader incorrectly judges freshness from the oldest market timestamp, so it did not use the locally fresh cache. A read-only rerun of the same registry, backtest, metrics, and score functions against `engine/data/yf_EURUSD=X_1d.csv` matched the existing JSON to floating-point precision. The audited cache has 777 UTC daily bars from 2023-07-20 through 2026-07-17.

Deterministic baseline rerun from repository root:

```bash
python engine/run_baseline.py --pair 'EURUSD=X' \
  --data-file 'engine/data/yf_EURUSD=X_1d.csv'
```

Two baseline reruns were byte-identical. Re-registering all five identical experiments preserved byte-identical registry JSON and IDs.

## Pipeline inventory

All five strategies are in `engine/strategies/registry.py`, use EURUSD (`EURUSD=X`) daily close data from yfinance, and emit continuous full-notional positions in `[-1, 0, 1]`. Execution is shifted to the next bar. There is no sizing, discrete stop-loss/take-profit, or strategy holding-period rule. A fixed 3 bps turnover cost comprises 2 bps spread, 1 bp slippage, and 0 bps commission; a direct reversal costs 6 bps. The configured minimum is 8 position-change observations. Development data is the full 2023-07-20..2026-07-17 range. Walk-forward validation uses rolling 252-bar train / 30-bar test / 30-bar step windows (17 non-overlapping OOS windows); no independent final held-out period was supplied to this run.

| Strategy | Indicators and rules | Default parameters | Eligibility |
|---|---|---|---|
| EMA crossover | Long fast EMA > slow EMA; short when below | fast 12, slow 26 | Passes current four gates |
| EMA trend pullback | EMA trend plus rolling-20 log-price z-score pullback | fast 12, slow 26, z 1.0 | Rejected |
| RSI mean reversion | Long RSI < 30; short RSI > 70 | period 14, 30/70 | Rejected |
| MACD trend confirmation | Position is sign of MACD histogram | 12/26/9 | Rejected |
| London breakout | Daily close beyond shifted prior 20-bar extreme plus 0.5 prior range; not a true London-session model | lookback 20, k 0.5 | Rejected |

## Reproduced strategy comparison

Returns and drawdowns are decimals. Gross loss and average loser are negative. “Trades” are exactly the existing metric's position-change-bar observations, not lifecycle trades. Average holding time is not computed by the existing backtester and is therefore `N/A`. Exposure was audited from OOS positions.

| Strategy | Trades | W/L | Win rate | Avg winner | Avg loser | Expectancy/obs | Gross profit | Gross loss | Net/OOS return | PF | Max DD | Avg hold | Exposure | In-sample return | Robustness | Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| EMA crossover | 30 | 14/16 | 0.466667 | 0.003688 | -0.002077 | 0.000614 | 0.051635 | -0.033226 | 0.064815 | 1.5541 | -0.093298 | N/A | 100.00% | 0.096275 | 0.490 | 56.66 |
| EMA trend pullback | 42 | 10/32 | 0.238095 | 0.005132 | -0.001551 | 0.000040 | 0.051319 | -0.049621 | -0.003538 | 1.0342 | -0.032807 | N/A | 8.43% | 0.000471 | 0.206 | 29.36 |
| RSI mean reversion | 57 | 15/42 | 0.263158 | 0.002711 | -0.001957 | -0.000729 | 0.040660 | -0.082207 | 0.009686 | 0.4946 | -0.029283 | N/A | 24.31% | 0.041436 | 0.000 | 30.09 |
| MACD trend confirmation | 68 | 33/35 | 0.485294 | 0.003235 | -0.004264 | -0.000625 | 0.106750 | -0.149228 | -0.126300 | 0.7153 | -0.175953 | N/A | 100.00% | -0.138294 | 0.206 | 17.85 |
| London breakout | 13 | 1/12 | 0.076923 | 0.007277 | -0.001982 | -0.001270 | 0.007277 | -0.023783 | -0.016446 | 0.3060 | -0.016446 | N/A | 1.37% | -0.019475 | 0.029 | 17.19 |

Walk-forward buy-and-hold returned 0.020852; only EMA crossover exceeded it. Gate failures (locked gates: score >= 40, robustness >= 0.3, OOS return > 0, PF >= 1.3): EMA crossover none; EMA pullback, MACD, and London fail all four; RSI fails score, robustness, and PF. London has only 13 observations—above configured 8 but below the scoring module's documented/default expectation of 20.

Baseline controls using identical backtester costs returned: no trade 0.000%, buy-and-hold 2.055%, fixed 20-period momentum 1.078%, and SMA 20/50 crossover 10.157%. EMA crossover returned 6.482%, below the simple SMA control. Fixed-seed randomized sanity controls circularly shift each strategy's positions, preserving position/run-length structure, turnover, and cost mechanics; they are controls only and are not registered strategies.

## Validation-integrity audit

- Look-ahead/future values: registry indicators use trailing EWM/rolling data; breakout extrema are shifted one bar; the backtester shifts every signal one bar. `held_out_validate` recomputes each future signal from observations available at that point. No direct look-ahead was found.
- Window overlap: the current 30/30 test/step configuration yields 17 non-overlapping windows with unique chained timestamps. Generic `step_days < test_days` silently duplicates OOS timestamps; a strict xfail test documents it.
- Split integrity: the full-period “in-sample” diagnostic overlaps walk-forward OOS dates. It is not an independent training result. No independent final holdout was used, so repeated human testing against the same period cannot be ruled out and watcher eligibility should be interpreted only as passage of the mechanical gates.
- Parameter selection: defaults are fixed in the registry and no automated search exists. There is no evidence of final-OOS tuning, but the absence of experiment history before this registry prevents proving that human selection never reused the period.
- Candle semantics: strategy testing is close-only and has no SL/TP, eliminating intrabar ordering claims. Paper validation also explicitly uses closes only. The last cached bar was a completed Friday bar as of Sunday audit time.
- Warm-up: 252 training bars exceed the longest 26/20-bar lookback. The first return in each test window is conservatively omitted by the inner one-bar shift.
- Data quality: timestamps are monotonic UTC; duplicates and OHLCV nulls are zero. Weekend gaps are expected. One gap longer than three days (2025-04-17..22) is plausibly Easter, but no FX calendar completeness validator exists.
- Costs: fixed spread and slippage are included and commission is explicitly zero. A constant daily 3 bps model does not represent session/volatility-dependent spread or market impact.
- Sample/regime risk: counts are modest (13–68). No regime-attribution analysis exists. Largest winning observation as a share of gross profit is EMA 14.7%, pullback 35.3%, RSI 23.5%, MACD 12.1%, London 100%; London is exceptional-winner dominated.
- Metric integrity: `trade_returns = strat[change > 0]` measures only position-change-bar return, not complete entry-to-exit P&L. Therefore trade count, win rate, PF, average win/loss, expectancy, and gross figures must not be interpreted as lifecycle trade statistics. RSI's positive compounded OOS return alongside negative turnover-observation expectancy illustrates the mismatch.
- Cache integrity: cache freshness is based on the CSV's first market timestamp rather than file freshness, forcing network refresh for a multi-year cache. A strict xfail test documents this concrete defect.

## Experiment registry

`engine/src/experiment_registry.py` writes strict canonical JSON under an exclusive file lock and atomically replaces artifacts. IDs are SHA-256 hashes of timestamp-free normalized experiment content, making repeat registration idempotent. Records include git/data hashes, complete parameters and context, boundaries, cost components, metrics, locked gate outcomes, status, rejection reasons, and artifacts. Missing/non-finite results fail closed; secret-shaped fields are rejected. A Markdown audit summary is emitted alongside the JSON. The CLI refuses to run unless paper-only configuration remains enabled. Current store: `engine/results/experiment_registry.json`; human summary: `engine/results/experiment_registry.md`.

## Next research recommendation

Recommend one family: **trend continuation with volatility and regime filtering**, evaluated first as a controlled extension of the existing trend evidence—not as an immediately tradeable strategy.

- Hypothesis: persistent EURUSD trends can support continuation, while volatility and regime filters reduce the full-time exposure and deep reversals seen in EMA/MACD.
- Evidence: EMA crossover is the only registered strategy passing all mechanical gates and beating buy-and-hold, but it trails SMA 20/50 and carries 100% exposure with 9.33% drawdown. MACD's large loss shows unfiltered trend confirmation is insufficient.
- Expected failure: whipsaw in range regimes, lag after volatility shocks, and apparent gains concentrated in one trend regime.
- Data: timestamp-clean EURUSD daily OHLC, bid/ask or defensible spread history, volatility/regime covariates, and at least 10 years spanning multiple rate/volatility regimes before reserving a never-touched final holdout.
- Initial ranges: trend horizon 20–100 bars; ATR/realized-volatility horizon 10–40 bars; volatility percentile gate 20th–80th; regime horizon 50–200 bars. Use coarse predeclared values, not a large sweep.
- Anti-overfitting: preregister hypotheses/ranges; nested walk-forward development; purge/embargo if labels overlap; one final holdout access; fixed cost stress tests at 3/5/10 bps; stability across subperiods and nearby parameters; compare to SMA and randomized controls.
- Minimum sample: at least 100 lifecycle trades, 30 per major regime, and 20 OOS windows before final holdout evaluation.
- Accept only if all locked gates pass on untouched final OOS, lifecycle PF >= 1.3, score >= 40, robustness >= 0.3, OOS return > 0, beats the SMA control after stressed costs, and no single trade contributes more than 20% of gross profit. Reject on any gate failure, regime dependence, material nearby-parameter instability, or cost-stress reversal.

## Unresolved risks

The exact online backtest remains unreproducible until DNS/cache freshness is fixed; cron daemon/scheduled proof is outside this sandbox; lifecycle trade metrics and average holding time are absent; no independent final holdout or regime attribution was produced; FX-session completeness and variable execution costs are not modeled. These limitations preclude a deployment claim despite EMA crossover's mechanical gate result.
