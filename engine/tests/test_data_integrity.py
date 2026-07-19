import pandas as pd
try:
    from engine.src.data_manifest import is_cache_fresh, build_manifest, last_fully_closed
except ModuleNotFoundError:
    from src.data_manifest import is_cache_fresh, build_manifest, last_fully_closed

def frame(index):
    return pd.DataFrame({"close": range(len(index))}, index=pd.to_datetime(index, utc=True))

def test_fresh_stale_empty_and_unsorted_duplicates():
    now = pd.Timestamp("2024-01-10 12:00", tz="UTC")
    assert is_cache_fresh(frame(["2024-01-09"]), "1d", now)
    assert not is_cache_fresh(frame(["2024-01-01"]), "1d", now)
    assert not is_cache_fresh(frame([]), "1d", now)
    m = build_manifest(frame(["2024-01-09", "2024-01-07", "2024-01-09"]),
                       source="csv", symbol="X", timeframe="1d", download_ts=now)
    assert m["duplicate_count"] == 1 and m["missing_interval_summary"]["gap_count"] == 1

def test_timezone_and_incomplete_latest_candle():
    now = pd.Timestamp("2024-01-10 12:00", tz="UTC")
    df = frame(["2024-01-09", "2024-01-10"])
    assert last_fully_closed(df, "1d", now) == pd.Timestamp("2024-01-09", tz="UTC")
    assert build_manifest(df, source="x", symbol="X", timeframe="1d", download_ts=now)["timezone"] == "UTC"
