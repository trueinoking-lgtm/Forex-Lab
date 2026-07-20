import pandas as pd
try:
    from engine.src.trade_ledger import extract_trades, lifecycle_metrics
except ModuleNotFoundError:
    from src.trade_ledger import extract_trades, lifecycle_metrics

def series(values):
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), tz="UTC"))

def test_long_short_flat_reversal_and_final_open():
    p = series([100, 101, 103, 102, 99, 98])
    trades = extract_trades(p, series([1, 1, -1, -1, 1, 1]), strategy="x", symbol="Y")
    assert trades[0]["direction"] == "long" and trades[0]["exit_reason"] == "reversal"
    assert trades[1]["direction"] == "short" and trades[1]["exit_reason"] == "reversal"
    assert trades[-1]["still_open_at_end"]
    assert trades[0]["entry_ts"] > trades[0]["signal_ts"]

def test_costs_and_closed_metrics():
    p = series([100, 100, 110, 110])
    t = extract_trades(p, series([1, 1, 0, 0]), strategy="x", symbol="Y",
                       spread_bps=2, slippage_bps=1, commission_bps=1)
    assert round(t[0]["total_cost"], 6) == 40.0
    m = lifecycle_metrics(t)
    assert m["trade_count"] == 1 and m["wins"] == 1

def test_no_nan_inf_and_empty():
    assert lifecycle_metrics([])["trade_count"] == 0
    assert extract_trades(series([1, 2]), series([0, 0]), strategy="x", symbol="Y") == []
