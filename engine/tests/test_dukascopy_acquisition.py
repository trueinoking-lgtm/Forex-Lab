import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

ENGINE = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("dukascopy_acquirer", ENGINE / "run_acquire_dukascopy.py")
duka = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(duka)


def candle(day, open_=1.10, high=1.12, low=1.09, close=1.11, volume=10):
    return {"timestamp": int(pd.Timestamp(day, tz="UTC").timestamp() * 1000),
            "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def response(status, payload):
    result = Mock(status_code=status)
    result.content = json.dumps(payload).encode()
    return result


def test_retry_uses_bounded_exponential_backoff():
    session = Mock()
    session.get.side_effect = [response(503, {}), response(429, {}), response(200, [candle("2020-01-02")])]
    sleeps = []
    got = duka.request_json(session, {"path": "api/historicalPrices"}, attempts=3, base_delay=1, sleep=sleeps.append)
    assert got[0]["open"] == 1.10
    assert len(sleeps) == 2 and 1 <= sleeps[0] <= 1.1 and 2 <= sleeps[1] <= 2.1


def test_path_is_appended_to_base_url_and_not_sent_as_query_param():
    session = Mock()
    session.get.return_value = response(200, [])
    duka.request_json(session, {"path": "api/instrumentList", "fields": "id,name"})
    args, kwargs = session.get.call_args
    assert args[0] == "https://freeserv.dukascopy.com/2.0/api/instrumentList"
    assert kwargs["params"] == {"fields": "id,name"}


@pytest.mark.parametrize("status", [204, 404])
def test_public_endpoint_unavailable_is_reported_honestly(status):
    session = Mock()
    unavailable = response(status, {})
    if status == 204:
        unavailable.content = b""
    else:
        unavailable.content = b"<html><body>nginx</body></html>"
    session.get.return_value = unavailable
    with pytest.raises(RuntimeError, match=rf"Dukascopy public endpoint unavailable \(HTTP {status}\)"):
        duka.request_json(session, {"path": "api/instrumentList"})
    assert session.get.call_count == 1


def test_atomic_write_replaces_complete_payload(tmp_path):
    target = tmp_path / "artifact.json"
    target.write_bytes(b"old")
    duka.atomic_write(target, b"complete")
    assert target.read_bytes() == b"complete"
    assert list(tmp_path.iterdir()) == [target]


def test_network_mocked_happy_path_writes_manifest_and_resumes(tmp_path, monkeypatch):
    payload = [candle("2020-01-02"), candle("2020-01-03")]
    session = Mock()
    session.get.side_effect = [response(200, [{"id": 42, "name": "EUR/USD"}]), response(200, payload)]
    monkeypatch.setattr(duka.time, "sleep", lambda _: None)
    output = tmp_path / "raw_dukascopy_EURUSD_1d.csv"
    frame, manifest = duka.acquire("2020-01-01", "2020-02-01", output, tmp_path / "chunks",
                                   session=session, now="2020-02-02T12:00:00Z")
    assert len(frame) == 2 and output.exists()
    stored = json.loads((tmp_path / "raw_dukascopy_EURUSD_1d.csv.manifest.json").read_text())
    assert stored["csv_sha256"] == duka.sha256_file(output)
    assert stored["session_boundary"] == "[00:00,24:00) UTC"
    assert manifest["invalid_ohlc_count"] == 0
    resumed = Mock()
    resumed.get.return_value = response(200, [{"id": 42, "name": "EUR/USD"}])
    duka.acquire("2020-01-01", "2020-02-01", output, tmp_path / "chunks",
                 session=resumed, now="2020-02-02T12:00:00Z")


def test_integrity_validation_and_incomplete_exclusion():
    payload = [candle("2020-01-03"), candle("2020-01-02"), candle("2020-01-02", close=1.105),
               candle("2020-01-04"), candle("2020-01-05")]
    frame = duka.normalize_candles(payload, start="2020-01-01", end="2020-01-06",
                                   now="2020-01-05T12:00:00Z")
    findings = duka.validate_integrity(frame, end="2020-01-06", now="2020-01-05T12:00:00Z")
    assert list(frame.index.day) == [2, 3, 4]
    assert findings["sorted"] and findings["unique"] and findings["invalid_ohlc_count"] == 0
    assert not findings["incomplete_latest_candle"]


def test_invalid_ohlc_is_rejected():
    frame = duka.normalize_candles([candle("2020-01-02", high=1.0)], start="2020-01-01",
                                   end="2020-02-01", now="2020-02-02T00:00:00Z")
    assert duka.validate_integrity(frame, end="2020-02-01", now="2020-02-02T00:00:00Z")["invalid_ohlc_count"] == 1


def test_module_has_no_execution_dependencies_or_sensitive_vocabulary():
    source = (ENGINE / "run_acquire_dukascopy.py").read_text().lower()
    forbidden = ("run_acquire_data", "src.", "metatrader5", "order" + "_send",
                 "account" + "_info", "positions" + "_get")
    assert not any(term in source for term in forbidden)
    assert set(sys.modules).isdisjoint({"MetaTrader5"})
