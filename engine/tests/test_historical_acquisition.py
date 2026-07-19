import importlib.util, sys
from pathlib import Path
import pandas as pd

ENGINE=Path(__file__).parents[1]
sys.path.insert(0,str(ENGINE))
from run_acquire_data import atomic_csv, latest_closed_day
from mt5_history_export import normalize_rates, sanitize

def test_atomic_csv_and_latest_closed(tmp_path):
    idx=pd.DatetimeIndex(["2026-01-01"],tz="UTC",name="timestamp")
    p=tmp_path/"x.csv"; atomic_csv(pd.DataFrame({"close":[1.]},index=idx),p)
    assert p.exists() and latest_closed_day("2026-01-02T12:00Z")==pd.Timestamp("2026-01-02",tz="UTC")

def test_mt5_normalization_excludes_cutoff_and_deduplicates():
    ts=int(pd.Timestamp("2020-01-02",tz="UTC").timestamp())
    rows=[{"time":ts,"open":1.,"high":2.,"low":.5,"close":1.5,"tick_volume":8},
          {"time":ts,"open":1.,"high":2.,"low":.5,"close":1.6,"tick_volume":9},
          {"time":int(pd.Timestamp("2020-01-03",tz="UTC").timestamp()),"open":1.,"high":2.,"low":.5,"close":1.5}]
    got=normalize_rates(rows,"2020-01-01","2020-01-03")
    assert len(got)==1 and got.index.tz is not None and got.iloc[0].close==1.6

def test_sanitize_does_not_expose_punctuation():
    assert sanitize("broker@example/token") == "broker_example_token"
