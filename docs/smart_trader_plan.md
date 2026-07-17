# Aether Forex Lab — "Smart Trader" Upgrade Plan

GOAL (Kade, verbatim intent): the lab should not just place demo orders; it should behave
like a disciplined, experienced trader whose PRIMARY job is *not going broke*. Not a
money-printer — a capital-preservation engine. Paper/backtest only (no live orders, ever).

RESEARCH GROUNDING (web, 2025-2026 consensus):
- Position sizing: fixed-fractional 0.5-1% account risk/trade is the defensive base.
  Fractional Kelly only as a *capped* variant. Capital preservation > growth.
- Walk-forward / out-of-sample is the gold-standard "BS detector" vs overfitting.
- Drawdown control: hard circuit breaker on max-drawdown + daily loss limit; server-side,
  non-overridable (like a kill switch) — halts NEW entries when breached.
- Regime filtering: ADX-based trend/range classification; skip unfavorable regimes.
- Honest metrics: profit factor >= 1.3, report max DD + Sharpe + sample size; FLAG
  overfitting warning signs (Sharpe>3, PF>4, winrate>80%, DD<5%, perfect curve).

EXISTING FOUNDATION (do NOT rewrite — extend/additive only):
- src/signals.py: risk_check (fixed-fractional, clips 0.5-1.0%), compute_sl_tp (ATR),
  regime gate (score_signal), PaperSignal dataclass.
- src/score.py: score_strategy (walk-forward OOS scoring + robustness penalty).
- engine/run_backtest.py: walk-forward backtest + buy&hold comparison.
- src/execution/guards.py: full pre-trade gate (demo-only, kill switch, stale, SL/TP,
  risk_check mandatory, paper-signal-required, max-open caps).
- config.yaml: paper_only=true, allow_live_orders=false, walk_forward config, risk_pct=0.75.

DESIGN PRINCIPLES:
1. Additive modules only. Never weaken guards.py or risk_check. New controls are EXTRA gates.
2. Every new control is fail-closed (default = refuse) and config-driven.
3. Paper/backtest only. No new network/broker paths. No price/filling logic changes.
4. All metrics reported honestly with overfitting warnings.

DELIVERABLES (3 build batches, each independently testable):

## Batch 1 — Risk & exposure hardening (foundation)
NEW src/execution/risk_budget.py:
  - PortfolioRiskState: tracks equity curve (list of equity points), peak equity (high-water
    mark), realized + open risk, daily PnL, per-strategy exposure.
  - max_drawdown_pct() from equity curve; daily_pnl(); current_open_risk().
  - Circuit-breaker check halt_new_entries() -> True when (a) drawdown from peak >=
    cfg max_drawdown_pct (default 6%) OR (b) daily_pnl <= -cfg daily_loss_limit_pct
    (default 3%) OR (c) total open risk >= cfg max_portfolio_risk_pct (default 4%).
  - update_equity(equity), register_open(order risk), register_close(pnl).
  - All thresholds from config.yaml [risk] block (add sensible defaults).
WIRE into guards.run_pretrade_guards: append a reject reason when PortfolioRiskState
  (passed in) says halt_new_entries(). Keep existing guards intact.
CONFIG: add [risk] max_drawdown_pct=6.0, daily_loss_limit_pct=3.0, max_portfolio_risk_pct=4.0,
  per_strategy_risk_pct (cap per strategy). risk_check already clips 0.5-1.0; extend to also
  respect per_strategy cap and max_portfolio_risk (reduce units if portfolio risk would exceed).
TESTS: risk_budget unit tests (DD breach halts, daily loss halts, open-risk cap), and a
  guards test that halt reason appears.

## Batch 2 — Regime intelligence + walk-forward trade gate
EXTEND src/signals.py:
  - adx(high,low,close,period=14) -> float; classify_regime(close,high,low) -> ("trend"|"range",
    adx_value). Trend when ADX>25, range when <=20 (hysteresis band 20-25 -> keep previous).
  - A strategy declares preferred_regime ("trend"|"range"|"any"). score_signal already zeroes
    score when regime disallowed; now drive regime_allowed from ADX measure, not a boolean flag.
  - NEW gate approve_for_trading(score_dict, robustness, oos_return, regime_match) -> bool:
    tradeable ONLY IF score >= cfg min_signal_score AND robustness >= cfg min_robustness
    (default 0.3) AND profit_factor >= 1.3 AND oos_return > 0 AND regime matches strategy's
    preferred_regime. This makes walk-forward approval a HARD trade gate.
WIRE: run_signals.py (or signal generation path) must call approve_for_trading before a
  PaperSignal is marked tradeable; non-approved signals are still recorded but flagged
  tradeable=False.
CONFIG: [signals] min_robustness=0.3, min_profit_factor=1.3.
TESTS: adx/classify_regime unit tests; approve_for_trading accept/reject cases.

## Batch 3 — Paper simulator + honest reporting + overfitting flags
NEW engine/src/paper_sim.py:
  - simulate(signals, price_series, cost_bps) -> equity curve + per-trade list. Uses
    compute_sl_tp/risk_check for sizing. Honors PortfolioRiskState (skip entry when halted).
  - metrics: total_return, sharpe, sortino, profit_factor, win_rate, max_drawdown,
    trade_count, avg_hold, expectancy.
  - overfitting_flags(list of warning strings) when: sharpe>3, profit_factor>4, win_rate>80%,
    max_drawdown<5%, equity curve too smooth (per-bar return std near 0), or OOS<<in-sample.
NEW engine/run_paper_sim.py (CLI): loads approved signals + yfinance price, runs simulate(),
  writes results/paper_sim_<pair>.json with equity curve + metrics + overfitting_flags.
  Refuses if paper_only false / live allowed (same SAFETY guard as run_trends.py).
EXTEND run_backtest.py output: include overfitting_flags + min_trades warning + robustness.
TESTS: paper_sim unit test on a synthetic series (known PF/DD), overfitting flag triggers.

VERIFICATION for every batch: pytest green (engine + PC bridge), diag OK, no price/filling
logic changed, no guard weakened. Commit per batch on the real repo after I verify the clone diff.

OUT OF SCOPE (explicitly): live orders, new broker adapters, changing FOK/IOC logic,
changing price=0 behavior, ML model training. This is risk-discipline + honesty, not a new
strategy engine.
