# Currency-Strength Research Phase 1 Checkpoint

**Date:** 2026-07-21  
**Classification:** 1. REJECT STRATEGY FAMILY

Research-only paper lab. This checkpoint does not claim profitability or authorize forward validation, signals, a watcher, or execution.

## Frozen design and data

The implementation follows the frozen preregistration: signed base/quote aggregation over the limited EURUSD, GBPUSD, USDJPY, and AUDUSD hub universe; equal-weight, volatility-normalized, and ranked-momentum methods; isolated continuation, volatility-filter, and trend-confirm filters; and next-H1-open execution. The 405 frozen configurations cover 5 lookbacks, 3 holdings, 3 ATR stops, 3 targets, 3 strength methods, and 3 filters. Fingerprints: `{"AUDUSD": "776a10f7326ba04bf68a7c95011aedeebee693b0c5eb22d2ea22a98332bb94a7", "EURUSD": "80cc20e9de10f929619902d618a32035f45d557751153d16484de46d8d5fcfc1", "GBPUSD": "99a2564ae0040d6c47ec20d1ce84c82a464be44dafac05898ea7e2e53d1fa789", "USDJPY": "3aad2f78b5b06f39ac7804d33845c40e31d2d00073937e2df8eb51512802db60"}`. Analysis folds are DEV 2022-01-03–2023-06-30, VALIDATION 2023-07-01–2024-12-31, and held-out TEST 2025-01-01–2026-07-17. Selection used DEV+VALIDATION only.

Strength is the equal average of signed containing-pair cumulative returns; volatility-normalized divides each pair return by its realized volatility; ranked momentum maps currency ranks to [0,1]. USDJPY uses the JPY pip multiplier (100), and all PnL is normalized equal-risk USD accounting v2.

## Selected research configuration and chronological result

Configuration: `{"atr_stop": 2.0, "filter": "continuation", "holding": 24, "lookback": 24, "method": "equal_weight", "target_r": 1.5}`. Aggregate chronological lifecycle metrics: PF 0.8432, return -281.9231%, expectancy USD/trade -4.4265, max drawdown 258.0106%, trades 6369, robustness 0.000, score 0.00. Per-pair PnL: `{"AUDUSD": -9735.716690257732, "EURUSD": -7070.555231593415, "GBPUSD": -10800.747478467614, "USDJPY": -585.2857390282769}`. These are research observations, not evidence of future profitability.

## Controls, stability, costs, and concentration

Randomized overall 90th-percentile PF: 0.5882. Five-bps PF: 0.7826; 12-bps PF: 0.2830; delayed PF: 0.8425. Pair gross-profit fractions: `{"AUDUSD": 0.319360181770686, "EURUSD": 0.17456055667477324, "GBPUSD": 0.17290167660590702, "USDJPY": 0.3331775849486338}`. Currency gross-profit fractions: `{"AUD": 0.159680090885343, "EUR": 0.08728027833738662, "GBP": 0.08645083830295351, "JPY": 0.1665887924743169, "USD": 0.5}`. Best trade concentration: 0.10%; best three: 0.29%. Period results, rolling 3y/5y diagnostics, and high/low-vol regimes are recorded in `currency_strength_period_stability.json`; 2010–2014 is N/A and is not fabricated.

## Gate outcome and unresolved risks

Failed gates: `["profit_factor_gte_1_3", "return_positive", "robustness_gte_0_3", "score_gte_40", "positive_at_least_3_pairs", "survives_5bps", "nearby_parameter_stability", "no_single_period_dependence"]`. The limited USD-hub universe creates structural USD dependence, missing crosses prevent a complete currency matrix, demo-history microstructure may differ from realizable costs, and randomized controls cannot eliminate selection bias. No live or paper-forward ledger paths were used.
