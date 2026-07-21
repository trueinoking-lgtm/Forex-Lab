import numpy as np
import pandas as pd

from strategies.currency_strength import (currency_strength, construct_signals,
    signed_currency_aggregation)
from run_currency_strength_research import metrics
from src.accounting import accounting_metadata


def prices(n=150):
    idx=pd.date_range("2025-01-01",periods=n,freq="h",tz="UTC")
    x=np.arange(n,dtype=float)
    return pd.DataFrame({"EURUSD":1.1*np.exp(.0002*x),"GBPUSD":1.3*np.exp(-.0001*x),
      "USDJPY":145*np.exp(.00015*x),"AUDUSD":.7*np.exp(.00005*x)},index=idx)


def test_no_lookahead_strength_at_t_unchanged_when_future_is_shifted():
    p=prices(); t=p.index[80]; original=currency_strength(p,24,"equal_weight").loc[t]
    altered=p.copy(); altered.loc[altered.index>t] *= 50
    pd.testing.assert_series_equal(original,currency_strength(altered,24,"equal_weight").loc[t])
    # The decision is also causal, not merely the strength helper.
    pd.testing.assert_series_equal(construct_signals(p,24,"equal_weight").loc[t],
      construct_signals(altered,24,"equal_weight").loc[t])


def test_cross_pair_base_quote_sign_correctness():
    x=pd.DataFrame({"EURUSD":[.01],"GBPUSD":[0],"USDJPY":[0],"AUDUSD":[0]})
    s=signed_currency_aggregation(x)
    assert s.loc[0,"EUR"] > 0 and s.loc[0,"USD"] < 0


def test_normalizations_are_finite_bounded_after_warmup():
    p=prices()
    vol=currency_strength(p,24,"vol_normalized").dropna()
    rank=currency_strength(p,24,"ranked_momentum").dropna()
    assert np.isfinite(vol.to_numpy()).all() and (vol.abs()<=10).all().all()
    assert ((rank>=0)&(rank<=1)).all().all()


def test_selection_contract_excludes_test_parameters():
    source=(__import__("pathlib").Path(__file__).parents[1]/"run_currency_strength_research.py").read_text()
    assert '"selection_basis":"DEV+VALIDATION only; TEST excluded"' in source
    assert "sel_pf=(fold_metrics[\"DEV\"]" in source


def test_cost_stress_pf_is_non_increasing():
    base=[{"net_pnl_usd":100-c,"pair":"EURUSD","direction":"long","holding_hours":1} for c in (3,3,3)]
    base += [{"net_pnl_usd":-50-c,"pair":"EURUSD","direction":"short","holding_hours":1} for c in (3,3)]
    high=[{**t,"net_pnl_usd":t["net_pnl_usd"]-9} for t in base]
    assert metrics(high)["profit_factor"] <= metrics(base)["profit_factor"]


def test_aggregate_pf_recomputed_from_combined_gross_not_pair_pf_average():
    trades=[{"net_pnl_usd":100,"pair":"EURUSD","direction":"long","holding_hours":1},
      {"net_pnl_usd":-50,"pair":"EURUSD","direction":"short","holding_hours":1},
      {"net_pnl_usd":10,"pair":"USDJPY","direction":"long","holding_hours":1},
      {"net_pnl_usd":-100,"pair":"USDJPY","direction":"short","holding_hours":1}]
    assert metrics(trades)["profit_factor"] == 110/150
    assert metrics(trades)["profit_factor"] != ((100/50)+(10/100))/2


def test_accounting_v2_metadata():
    record=accounting_metadata(has_explicit_stop=True)
    assert record["accounting_version"]==2
    assert record["accounting_model"]=="normalized_equal_risk_v1"
