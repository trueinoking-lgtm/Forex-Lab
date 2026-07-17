# Smart Trader — Batch 4 addendum: held-out future validation + live-readiness

CONTEXT (verified from source): the lab ALREADY does honest walk-forward OOS backtesting
(src/backtest.py walk_forward trains on train_days, evaluates ONLY test_days; no leakage)
over 3y of real yfinance data (config lookback_days=1095). paper_sim.simulate does
point-in-time SL/TP fills; metrics.py is honest. So this batch does NOT rebuild backtesting —
it ADDS the "predict then fast-forward and score" truth test Kade asked for, plus a readiness gate.

Kade's words: "backtest and paper trades must simulate strategies and real markets... try to
place in a market a year [ago] and see if your predictions were correct... goal is for it to be
good enough that when I decide to live trade it's capable... link to demo account before live,
should go with flying colors."

DESIGN (additive, paper/backtest only, no broker/price/filling changes):

## 4a — engine/src/validation.py (NEW): held-out future truth test
  def held_out_validate(price: pd.Series, signal_fn, ctx: dict, cutoff: pd.Timestamp,
                        train_lookback_days: int = 756) -> dict:
      # Train signal_fn on price up to (cutoff - margin) using only data BEFORE cutoff.
      # Then evaluate the SAME signal logic on price AFTER cutoff (pure OOS, unseen).
      # Returns {equity, returns, trades, metrics (from metrics.summary),
      #          directional_accuracy, prediction_hits}.
      # Guard: if cutoff is inside price range with insufficient future window -> refuse
      # (raise ValueError "not enough held-out future data").
  def directional_accuracy(trades: list[dict]) -> dict:
      # trades from paper_sim.simulate (have side, reason=stop_loss|take_profit, pnl).
      # "prediction correct" = trade hit take_profit (target reached) OR exited with pnl>0.
      # Returns {hit_rate, take_profit_hits, stop_loss_hits, avg_pnl, n}.
      # hit_rate = fraction of trades that were profitable (prediction direction was right).
      # This is the "were my predictions correct" score Kade asked for.

## 4b — engine/src/live_readiness.py (NEW): single go/no-go gate
  def readiness_report(*, walk_forward_score, robustness, oos_return,
                       held_out_metrics: dict, directional_accuracy: dict,
                       max_drawdown_limit: float = 0.08,
                       min_profit_factor: float = 1.3,
                       min_directional_hit: float = 0.5,
                       regime_fit: bool = True) -> dict:
      # go = ALL: walk_forward_score>=40 AND robustness>=0.3 AND oos_return>0
      #         AND held_out_metrics.total_return>0 AND held_out max_drawdown>= -limit
      #         AND profit_factor>=min_profit_factor
      #         AND directional_accuracy.hit_rate>=min_directional_hit
      #         AND regime_fit
      # Returns {go: bool, reasons: list[str] (why pass/fail each), score: float}.
      # Fail-closed: any missing/nan -> go=False with reason.
  This is the "flying colors" verdict: a strategy earns live/demo linking ONLY if it survived
  walk-forward AND the held-out future AND hit its predictions directionally.

## 4c — engine/run_validate.py (NEW CLI, paper-only SAFETY guard like run_trends.py)
  - argparse --pair (default EURUSD=X) --cutoff YYYY-MM-DD (default: 1 year before last data)
    --train-lookback-days (default 756).
  - SAFETY: refuse if not paper_only or allow_live_orders.
  - For each strategy in strategies.registry: walk_forward (in-sample vs OOS via run_backtest
    logic), then held_out_validate on cutoff, compute directional_accuracy, then readiness_report.
  - Write results/readiness_<pair>.json with per-strategy: walk_forward score, robustness,
    oos_return, held_out metrics, directional hit_rate, go/no-go + reasons.
  - Print a summary table.
  - Handles yfinance fetch (load_pair) + cache.

## 4d — extend engine/run_backtest.py output (additive)
  - Include directional_accuracy when signals/trades available (reuse paper_sim.simulate on the
    OOS equity to get trades, then directional_accuracy). Add to per-strategy result.
  - Backtest MATH unchanged.

TESTS: engine/tests/test_validation.py (NEW): held_out_validate refuses on insufficient future
  data; accepts a clean train/test split; directional_accuracy computes hit_rate; readiness_report
  go/no-go on known-good and known-bad inputs; fail-closed on nan.

VERIFICATION each step: pytest green (engine + PC bridge), diag OK, no price/filling/volume logic
changed, no guard weakened. Commit per sub-batch on real repo after clone diff verified.

OUT OF SCOPE: live orders, broker adapters, changing FOK/IOC, ML training, changing existing
walk_forward math. This is the truth/validation layer on top of the existing honest backtester.
