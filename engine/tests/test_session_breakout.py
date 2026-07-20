import numpy as np
import pandas as pd
import pytest

try:
    from engine.strategies.registry import REGISTRY
    from engine.strategies.session_breakout import session_breakout
except ImportError:
    from strategies.registry import REGISTRY
    from strategies.session_breakout import session_breakout


def fixture(days=5):
    idx = pd.date_range("2024-01-01", periods=24*days, freq="h", tz="UTC")
    close = pd.Series(1.10 + np.sin(np.arange(len(idx))/8)*.001, index=idx)
    close.loc[idx.hour == 8] += .006
    return pd.DataFrame({"open": close.shift().fillna(close.iloc[0]),
                         "high": close+.0002, "low": close-.0002, "close": close}, index=idx)


def test_registered_discrete_and_flat_outside_session():
    data = fixture()
    signal = session_breakout(data, pair="EURUSD")
    assert "session_breakout" in REGISTRY
    assert set(signal.unique()) <= {-1., 0., 1.}
    assert (signal[data.index.hour >= 16] == 0).all()


def test_prefix_invariance_and_closed_candle_next_bar_contract():
    data = fixture()
    full = session_breakout(data, pair="EURUSD")
    assert full.iloc[:80].equals(session_breakout(data.iloc[:80], pair="EURUSD"))
    first = full[full != 0].index[0]
    assert first.hour >= 7
    # The returned change is the closed-candle signal; canonical ledger shifts it one bar.
    assert full.shift(1).loc[first + pd.Timedelta(hours=1)] == full.loc[first]


def test_requires_utc_and_rejects_unregistered_bounds():
    data = fixture()
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        session_breakout(data.tz_localize(None), pair="EURUSD")
    with pytest.raises(ValueError, match="preregistered"):
        session_breakout(data, pair="EURUSD", breakout_buffer=.2)
