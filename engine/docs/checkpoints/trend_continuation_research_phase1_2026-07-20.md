> **SUPERSEDED — accounting only (2026-07-20).** Preserve all original metrics and classification below as historical record. PF, expectancy, gross PnL, and concentration used `legacy_raw_price_units_v1` (version 1). The corrected trend-continuation classification is **rejected** under `normalized_equal_risk_v1` (version 2); see [Canonical accounting migration](canonical_accounting_migration_2026-07-20.md).

# Trend-continuation research — Phase 1 (2026-07-20)

Research/paper/demo only. No order endpoint was called and no order was placed.

## Protocol and selection

Canonical input: `4297` bars, `2010-01-04T00:00:00+00:00` through `2026-07-17T00:00:00+00:00`; SHA-256 verified.
The deliberate coarse subset contains **256** candidates (8 fast/slow extreme-spanning pairs x 2 ADX x 2 ATR x 2 vol floors x 2 stop extremes x 2 trailing; vol lookback 20 and ceiling 90 fixed).
Chronological partitions are earliest 60% development, middle 20% validation, latest 20% held-out test. Each partition uses the existing 252/63/63 walk-forward engine.
Selection requires all four locked canonical gates on validation, then ranks by `robustness * sign(score)`, lifecycle PF, and deterministic parameter JSON; return is not a ranking key. If none passes, the family is rejected and the top diagnostic candidate is reported without promotion.

## Selected diagnostic candidate

Parameters: `{"adx_threshold": 18, "atr_lookback": 14, "fast": 8, "slow": 40, "stop_atr": null, "trailing": true, "vol_high_pct": 90, "vol_lookback": 20, "vol_low_pct": 20}`

Validation gates passed: **True**. Classification: **1 REJECT STRATEGY FAMILY**.

### Per-fold lifecycle metrics

| Partition/fold | Dates | Trades | W/L | PF | Expectancy | Avg hold | Return | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| development/1 | 2010-12-22..2011-03-18 | 2 | 0/2 | 0.0 | -0.023792 | 10.5 | -0.0263 | -0.0263 |
| development/2 | 2011-03-21..2011-06-15 | 3 | 0/3 | 0.0 | -0.020170 | 9.3 | -0.0430 | -0.0625 |
| development/3 | 2011-06-16..2011-09-12 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/4 | 2011-09-13..2011-12-08 | 4 | 2/2 | 1.7054085665316434 | 0.006932 | 5.0 | -0.0131 | -0.0516 |
| development/5 | 2011-12-09..2012-03-06 | 5 | 2/3 | 0.0876210561175831 | -0.009775 | 5.0 | -0.0280 | -0.0458 |
| development/6 | 2012-03-07..2012-06-01 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/7 | 2012-06-04..2012-08-29 | 2 | 1/1 | 0.22172479387864902 | -0.005832 | 19.5 | -0.0117 | -0.0281 |
| development/8 | 2012-08-30..2012-11-26 | 5 | 2/3 | 0.8252027421771828 | -0.000875 | 4.4 | 0.0027 | -0.0205 |
| development/9 | 2012-11-27..2013-02-22 | 1 | 1/0 | None | 0.031308 | 32.0 | 0.0235 | -0.0214 |
| development/10 | 2013-02-25..2013-05-22 | 1 | 0/1 | 0.0 | -0.004592 | 32.0 | -0.0021 | -0.0233 |
| development/11 | 2013-05-23..2013-08-19 | 3 | 1/2 | 0.4153351032570184 | -0.010716 | 6.3 | -0.0343 | -0.0382 |
| development/12 | 2013-08-20..2013-11-14 | 2 | 1/1 | 0.21804000677902338 | -0.004905 | 5.5 | -0.0177 | -0.0194 |
| development/13 | 2013-11-15..2014-02-12 | 1 | 0/1 | 0.0 | -0.002235 | 5.0 | -0.0052 | -0.0089 |
| development/14 | 2014-02-13..2014-05-12 | 3 | 2/1 | 0.78733826209713 | -0.000759 | 2.0 | -0.0019 | -0.0059 |
| development/15 | 2014-05-13..2014-08-07 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/16 | 2014-08-08..2014-11-04 | 3 | 1/2 | 1.7463664009077522 | 0.004033 | 4.3 | 0.0380 | -0.0034 |
| development/17 | 2014-11-05..2015-02-03 | 2 | 1/1 | 56.31880092962324 | 0.046546 | 12.5 | 0.0738 | -0.0094 |
| development/18 | 2015-02-04..2015-05-01 | 3 | 2/1 | 299.7269392337374 | 0.015526 | 3.0 | 0.0601 | -0.0122 |
| development/19 | 2015-05-04..2015-07-29 | 2 | 1/1 | 0.07559824228102703 | -0.011137 | 9.5 | -0.0307 | -0.0558 |
| development/20 | 2015-07-30..2015-10-26 | 1 | 0/1 | 0.0 | -0.007559 | 1.0 | -0.0181 | -0.0181 |
| development/21 | 2015-10-27..2016-01-25 | 3 | 1/2 | 1.585287530868949 | 0.003099 | 10.0 | 0.0170 | -0.0295 |
| development/22 | 2016-01-26..2016-04-21 | 1 | 0/1 | 0.0 | -0.012578 | 5.0 | -0.0197 | -0.0197 |
| development/23 | 2016-04-22..2016-07-19 | 2 | 0/2 | 0.0 | -0.009416 | 2.0 | -0.0040 | -0.0074 |
| development/24 | 2016-07-20..2016-10-14 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/25 | 2016-10-17..2017-01-11 | 1 | 1/0 | None | 0.050947 | 50.0 | 0.0453 | -0.0210 |
| development/26 | 2017-01-12..2017-04-10 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/27 | 2017-04-11..2017-07-06 | 1 | 1/0 | None | 0.031553 | 32.0 | 0.0324 | -0.0114 |
| development/28 | 2017-07-07..2017-10-03 | 1 | 1/0 | None | 0.039058 | 56.0 | 0.0390 | -0.0158 |
| development/29 | 2017-10-04..2018-01-02 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/30 | 2018-01-03..2018-03-30 | 5 | 3/2 | 1.8590420330475361 | 0.002679 | 3.8 | 0.0330 | -0.0079 |
| development/31 | 2018-04-02..2018-06-27 | 1 | 1/0 | None | 0.008009 | 11.0 | 0.0073 | -0.0119 |
| development/32 | 2018-06-28..2018-09-24 | 1 | 0/1 | 0.0 | -0.024941 | 6.0 | -0.0175 | -0.0221 |
| development/33 | 2018-09-25..2018-12-20 | 3 | 1/2 | 0.07936573162985872 | -0.007573 | 3.7 | -0.0118 | -0.0209 |
| development/34 | 2018-12-21..2019-03-21 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/35 | 2019-03-22..2019-06-18 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| development/36 | 2019-06-19..2019-09-13 | 2 | 0/2 | 0.0 | -0.004956 | 1.5 | -0.0199 | -0.0199 |
| validation/1 | 2020-11-25..2021-02-23 | 2 | 1/1 | 0.80616299090313 | -0.000781 | 16.5 | 0.0096 | -0.0202 |
| validation/2 | 2021-02-24..2021-05-21 | 2 | 1/1 | 0.7912696058923612 | -0.001254 | 9.5 | -0.0115 | -0.0235 |
| validation/3 | 2021-05-24..2021-08-18 | 2 | 1/1 | 2.1165823828391033 | 0.003488 | 11.0 | 0.0025 | -0.0105 |
| validation/4 | 2021-08-19..2021-11-15 | 2 | 0/2 | 0.0 | -0.001598 | 2.5 | -0.0028 | -0.0048 |
| validation/5 | 2021-11-16..2022-02-10 | 1 | 0/1 | 0.0 | -0.007138 | 7.0 | -0.0044 | -0.0081 |
| validation/6 | 2022-02-11..2022-05-10 | 1 | 1/0 | None | 0.034303 | 17.0 | 0.0260 | -0.0118 |
| validation/7 | 2022-05-11..2022-08-05 | 4 | 1/3 | 0.7118393299155094 | -0.000942 | 4.2 | 0.0020 | -0.0229 |
| validation/8 | 2022-08-08..2022-11-02 | 1 | 0/1 | 0.0 | -0.000699 | 12.0 | -0.0154 | -0.0220 |
| validation/9 | 2022-11-03..2023-01-30 | 1 | 1/0 | None | 0.006924 | 15.0 | 0.0380 | -0.0087 |
| held_out_test/1 | 2024-03-15..2024-06-11 | 1 | 1/0 | None | 0.000330 | 9.0 | -0.0102 | -0.0107 |
| held_out_test/2 | 2024-06-12..2024-09-06 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0064 | -0.0134 |
| held_out_test/3 | 2024-09-09..2024-12-04 | 3 | 3/0 | None | 0.010775 | 4.0 | 0.0226 | -0.0052 |
| held_out_test/4 | 2024-12-05..2025-03-04 | 5 | 4/1 | 1.5783396154448504 | 0.001813 | 4.0 | 0.0039 | -0.0254 |
| held_out_test/5 | 2025-03-05..2025-05-30 | 3 | 2/1 | 23.89896578621498 | 0.020423 | 3.7 | 0.0184 | -0.0154 |
| held_out_test/6 | 2025-06-02..2025-08-27 | 5 | 2/3 | 1.0791898141235428 | 0.000198 | 4.0 | -0.0300 | -0.0417 |
| held_out_test/7 | 2025-08-28..2025-11-24 | 0 | 0/0 | None | 0.000000 | 0.0 | 0.0000 | 0.0000 |
| held_out_test/8 | 2025-11-25..2026-02-23 | 1 | 1/0 | None | 0.007845 | 11.0 | 0.0045 | -0.0217 |
| held_out_test/9 | 2026-02-24..2026-05-21 | 2 | 1/1 | 0.304561963833257 | -0.003565 | 10.5 | -0.0078 | -0.0240 |

## Aggregate and frozen baselines

| Strategy | Trades | W/L | PF | Expectancy | Return | Max DD | Exposure | Robustness | Score | Best/Best-3 GP | Gates |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| trend_continuation | 126 | 60/66 | 1.261820626478918 | 0.001527 | 0.0312 | -0.1514 | 0.266 | 0.312 | 46.68 | 0.102/0.218 | {'score_gte_40': True, 'robustness_gte_0_3': True, 'oos_return_gt_0': True, 'profit_factor_gte_1_3': False} |
| ema_crossover | 148 | 49/99 | 1.05333659668466 | 0.000545 | -0.3010 | -0.4208 | 1.000 | 0.227 | 22.89 | 0.149/0.309 | {'score_gte_40': False, 'robustness_gte_0_3': False, 'oos_return_gt_0': False, 'profit_factor_gte_1_3': False} |
| simple_ma_crossover | 94 | 33/61 | 1.0884235675111273 | 0.001077 | -0.0764 | -0.2638 | 0.988 | 0.227 | 27.06 | 0.196/0.376 | {'score_gte_40': False, 'robustness_gte_0_3': False, 'oos_return_gt_0': False, 'profit_factor_gte_1_3': False} |
| buy_and_hold | 0 | 0/0 | None | 0.000000 | -0.1081 | -0.3300 | 1.000 | 0.0 | 0.0 | 0.000/0.000 | {'score_gte_40': False, 'robustness_gte_0_3': False, 'oos_return_gt_0': False, 'profit_factor_gte_1_3': False} |
| no_trade | 0 | 0/0 | None | 0.000000 | 0.0000 | 0.0000 | 0.000 | 0.0 | 0.0 | 0.000/0.000 | {'score_gte_40': False, 'robustness_gte_0_3': False, 'oos_return_gt_0': False, 'profit_factor_gte_1_3': False} |
| fixed_seed_randomized_entry | 149 | 79/70 | 1.0464343479717557 | 0.000521 | 3.0532 | -0.2211 | 1.000 | 0.797 | 76.89 | 0.056/0.154 | {'score_gte_40': True, 'robustness_gte_0_3': True, 'oos_return_gt_0': True, 'profit_factor_gte_1_3': False} |

## Stability, regimes, and cost stress

Nearby stability: `{'neighbor_count': 7, 'median_neighbor_pf': 1.108660008580051, 'median_neighbor_return': 0.0318738728683019, 'pass': True}`

Regime results: `{'trend': {'lifecycle': {'trade_count': 62, 'wins': 22, 'losses': 40, 'win_rate': 0.3548387096774194, 'gross_profit': 0.3607888559999998, 'gross_loss': 0.4676625769999994, 'profit_factor': 0.7714725824640877, 'avg_winner': 0.016399493454545448, 'avg_loser': -0.011691564424999985, 'expectancy': -0.0017237696935483795, 'largest_winner': 0.06318484199999994, 'largest_loser': -0.0366795, 'largest_trade_gross_profit_pct': 0.17512969413888982, 'max_consecutive_wins': 3, 'max_consecutive_losses': 7, 'open_trade_count': 0, 'best_3_gross_profit_pct': 0.41114652665435936, 'avg_holding_bars': 6.838709677419355}, 'total_return': -0.024100835837312262, 'max_drawdown': -0.13077648213984427, 'exposure': 0.09867349313474517, 'robustness': 0.109, 'score': 24.47, 'gates': {'score_gte_40': False, 'robustness_gte_0_3': False, 'oos_return_gt_0': False, 'profit_factor_gte_1_3': False}, 'eligible': False, 'rejection_reasons': ['score_gte_40', 'robustness_gte_0_3', 'oos_return_gt_0', 'profit_factor_gte_1_3']}, 'range': {'lifecycle': {'trade_count': 103, 'wins': 52, 'losses': 51, 'win_rate': 0.5048543689320388, 'gross_profit': 0.44152616199999906, 'gross_loss': 0.3676127809999994, 'profit_factor': 1.2010631425788207, 'avg_winner': 0.008490887730769213, 'avg_loser': -0.007208093745098027, 'expectancy': 0.0007176056407766961, 'largest_winner': 0.04219356999999981, 'largest_loser': -0.023627331000000043, 'largest_trade_gross_profit_pct': 0.0955630121868065, 'max_consecutive_wins': 10, 'max_consecutive_losses': 8, 'open_trade_count': 1, 'best_3_gross_profit_pct': 0.22280467040591828, 'avg_holding_bars': 2.436893203883495}, 'total_return': -0.10714863827574339, 'max_drawdown': -0.12441620792613906, 'exposure': 0.0588782871771003, 'robustness': 0.125, 'score': 29.05, 'gates': {'score_gte_40': False, 'robustness_gte_0_3': False, 'oos_return_gt_0': False, 'profit_factor_gte_1_3': False}, 'eligible': False, 'rejection_reasons': ['score_gte_40', 'robustness_gte_0_3', 'oos_return_gt_0', 'profit_factor_gte_1_3']}}`

| Scenario | PF | Return | Max DD |
|---|---:|---:|---:|
| 3bps_standard | 1.261820626478918 | 0.03117633248402374 | -0.15140151180148675 |
| 5bps_total | 1.2164372038625173 | -0.018360477958398902 | -0.16220668619526202 |
| 8bps_total | 1.1518197394133216 | -0.08825750221742223 | -0.17816135693004176 |
| 12bps_total | 1.0717011047031122 | -0.17380372355371843 | -0.1989704991192821 |
| doubled_spread | 1.2388945121052102 | 0.006104407243710863 | -0.15682111124821307 |
| doubled_slippage | 1.2388945121052102 | 0.006104407243710863 | -0.15682111124821307 |
| extra_execution_bar | 1.139760397430909 | 0.13508148606027248 | -0.13840259982573222 |

## Rejection rules and classification

- lifecycle_pf_gte_1_3: **FAIL**
- walk_forward_return_gt_0: **PASS**
- robustness_gte_0_3: **PASS**
- score_gte_40: **PASS**
- closed_trades_gte_100: **PASS**
- largest_trade_lte_20pct_gross_profit: **PASS**
- not_one_short_period_or_regime: **PASS**
- nearby_parameters_do_not_collapse: **PASS**
- reasonable_cost_stress: **FAIL**
- not_materially_below_simple_ma: **PASS**

Final classification: **1 REJECT STRATEGY FAMILY**. At least one non-negotiable rejection rule failed; no candidate is promoted.

Safety confirmation: `paper_only=true`, `allow_live_orders=false`, and locked gates are unchanged. Watcher, cron, bridge, filling, zero-spread, retcodes, signal timestamps, execution code, and the forward-validation ledger were untouched. The canonical dataset and all other inputs were untouched.
