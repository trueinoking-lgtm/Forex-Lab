# Kronos Phase 1 — Preregistration
# Frozen: 2026-07-25
# Status: AWAITING REVIEW

## 1. Frozen Configuration
- Model: NeoQuasar/Kronos-mini (NeoQuasar/Kronos-Tokenizer-2k)
- device: cpu
- lookback: 256
- prediction_horizon: 5
- T: 1.0
- top_p: 0.9
- sample_count: 1
- numpy_seed: 20260725
- torch_seed: 20260725

## 2. Datasets (D1, OHLC only)
| Pair | Path | SHA-256 |
|---|---|---|
| EURUSD | data/yf_EURUSD=X_1d.csv | ce58f0bd2b8b5db... |
| GBPUSD | (record separately) | |
| USDJPY | (record separately) | |
| AUDUSD | (record separately) | |

## 3. Walk-Forward Design
- Chronological only
- Development period: first portion of data
- Validation period: middle portion
- Final test period: last portion (SEALED)
- Each fold: 256 input bars -> predict next 5 real recorded timestamps
- No weekend timestamps constructed
- No future data in preprocessing

## 4. Baselines (preregistered, frozen)
1. last-value forecast (forecast = last observed close)
2. random-walk forecast (forecast = last close + N(0, sigma))
3. drift forecast (forecast = last close + mean daily return * horizon)
4. rolling-mean forecast (forecast = trailing 20-day mean)
5. fixed EMA forecast (forecast = 20-day EMA)

## 5. Metrics
Per pair, fold, horizon:
- close-price MAE
- close-price RMSE
- normalized close MAE (MAE / range of closing prices)
- return MAE
- directional accuracy (sign of next-day return)
- high / low interval coverage (does realized price fall within predicted [low, high]?)
- OHLC validity rate
- inference duration (seconds)
- forecast failure count

Aggregate across all 4 pairs.

## 6. Decision Rules
Advance only if:
- Zero look-ahead leakage
- Results reproduce from stored forecasts
- OHLC validity ~100%
- Kronos beats last-value baseline on aggregate normalized error
- Improvement across multiple pairs and folds
- Final test does not reverse validation conclusion