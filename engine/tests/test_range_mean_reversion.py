import numpy as np
import pandas as pd

try:
    from engine.strategies.range_mean_reversion import (_wilder_atr_adx,
        bollinger_range_reversion, rsi_range_reversion, zscore_range_reversion)
    from engine.strategies.registry import REGISTRY
    from engine.src.canonical_eval import evaluate_strategy_canonical
    from engine.src.trade_ledger import extract_trades
except ImportError:
    from strategies.range_mean_reversion import (_wilder_atr_adx,
        bollinger_range_reversion, rsi_range_reversion, zscore_range_reversion)
    from strategies.registry import REGISTRY
    from src.canonical_eval import evaluate_strategy_canonical
    from src.trade_ledger import extract_trades


def prices(n=800):
    rng = np.random.default_rng(4)
    return pd.Series(1.1 + np.cumsum(rng.normal(0, .002, n)),
                     index=pd.date_range("2018-01-01", periods=n, freq="D"))


def test_registered_and_positions_are_discrete():
    for name in ("rsi_range_reversion", "zscore_range_reversion", "bollinger_range_reversion"):
        fn, kw = REGISTRY[name]
        assert set(fn(prices(), **kw).unique()) <= {-1.0, 0.0, 1.0}


def test_no_lookahead_prefix_invariance():
    p = prices()
    for fn in (rsi_range_reversion, zscore_range_reversion, bollinger_range_reversion):
        assert fn(p).iloc[:500].equals(fn(p.iloc[:500]))


def test_flat_outside_range():
    p = prices()
    for fn in (rsi_range_reversion, zscore_range_reversion, bollinger_range_reversion):
        assert (fn(p, adx_threshold=0) == 0).all()


def test_ledger_and_canonical_end_to_end():
    p = prices(); sig = zscore_range_reversion(p, adx_threshold=100)
    ledger = extract_trades(p, sig, strategy="test", symbol="EURUSD")
    assert all(t["entry_ts"] > t["signal_ts"] for t in ledger)
    ctx = {"walk_forward": {"train_days": 252, "test_days": 63, "step_days": 63},
           "cost_bps": 3, "initial_capital": 10000, "periods_per_year": 252,
           "risk_free_rate": 0, "min_trades": 20}
    result = evaluate_strategy_canonical(p, zscore_range_reversion, ctx,
        strategy="zscore_range_reversion", symbol="EURUSD")
    assert set(result["gates"]) == {"score_gte_40", "robustness_gte_0_3", "oos_return_gt_0", "profit_factor_gte_1_3"}


def test_seeded_random_control_is_reproducible_and_aligned():
    p = prices(); rng1 = np.random.default_rng(7); rng2 = np.random.default_rng(7)
    a = pd.Series(rng1.choice([-1., 0., 1.], len(p), p=[.05, .9, .05]), index=p.index)
    b = pd.Series(rng2.choice([-1., 0., 1.], len(p), p=[.05, .9, .05]), index=p.index)
    assert a.equals(b) and a.index.equals(p.index)
