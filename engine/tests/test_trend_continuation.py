import numpy as np
import pandas as pd

try:
    from engine.strategies.registry import REGISTRY
    from engine.strategies.trend_continuation import trend_continuation
    from engine.src.canonical_eval import evaluate_strategy_canonical
    from engine.src.trade_ledger import extract_trades
except ModuleNotFoundError:
    from strategies.registry import REGISTRY
    from strategies.trend_continuation import trend_continuation
    from src.canonical_eval import evaluate_strategy_canonical
    from src.trade_ledger import extract_trades


def _series(values):
    return pd.Series(values, index=pd.date_range("2020-01-01", periods=len(values), tz="UTC"), dtype=float)


def _price(n=900):
    rng = np.random.default_rng(23)
    returns = 0.00025 + rng.normal(0, 0.006, n)
    return _series(1.1 * np.exp(np.cumsum(returns)))


def test_signal_shape_domain_and_registry_entry():
    price = _price()
    signal = trend_continuation(price)
    assert signal.index.equals(price.index)
    assert signal.notna().all()
    assert set(signal.unique()) <= {-1.0, 0.0, 1.0}
    assert REGISTRY["trend_continuation"][0] is trend_continuation


def test_signal_does_not_peek_into_future():
    price = _price()
    cutoff = 700
    prefix = trend_continuation(price.iloc[:cutoff])
    changed_future = price.copy()
    changed_future.iloc[cutoff:] *= np.linspace(1, 4, len(price) - cutoff)
    full = trend_continuation(changed_future)
    pd.testing.assert_series_equal(prefix, full.iloc[:cutoff])


def test_flat_in_ranging_or_low_volatility_prices():
    flat = _series(np.ones(900))
    ranging = _series(1.0 + 0.001 * np.sin(np.arange(900) / 2.0))
    assert (trend_continuation(flat) == 0).all()
    assert (trend_continuation(ranging, adx_threshold=99) == 0).all()


def test_ledger_extraction_produces_valid_trades():
    price = _price(1200)
    signal = trend_continuation(price, adx_threshold=0, vol_low_pct=0, vol_high_pct=100,
                                stop_atr=None)
    trades = extract_trades(price, signal, strategy="trend_continuation", symbol="EURUSD",
                            spread_bps=2, slippage_bps=1, close_at_end=True)
    assert trades
    assert all(t["holding_bars"] >= 0 and np.isfinite(t["net_pnl"]) for t in trades)


def test_canonical_eval_end_to_end():
    price = _price(1000)
    ctx = {"walk_forward": {"train_days": 252, "test_days": 63, "step_days": 63},
           "cost_bps": 3, "initial_capital": 10000, "periods_per_year": 252,
           "risk_free_rate": 0, "min_trades": 1}
    result = evaluate_strategy_canonical(price, trend_continuation, ctx,
                                         strategy="trend_continuation", symbol="EURUSD",
                                         spread_bps=2, slippage_bps=1)
    assert "lifecycle_metrics" in result
    assert isinstance(result["trades"], list)
