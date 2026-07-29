"""Isolated contract tests for the sanitized read-only D1 metadata endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import server


@dataclass
class FakeAccount:
    trade_mode: int = 0
    company: str = "MetaQuotes Ltd."
    server: str = "MetaQuotes-Demo"
    login: int = 123456
    balance: float = 10000.0
    equity: float = 10000.0
    currency: str = "USD"


class FakeMT5:
    TIMEFRAME_D1 = 16408

    def __init__(self, *, trade_mode=0, rates=None):
        self.info = FakeAccount(trade_mode=trade_mode)
        self.rates = rates if rates is not None else [
            {"time": 1785362400},
            {"time": 1785276000},
            {"time": 1785448800},
        ]
        self.copy_calls = []
        self.order_calls = 0

    def account_info(self):
        return self.info

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.copy_calls.append((symbol, timeframe, start, count))
        return self.rates

    def order_send(self, *args, **kwargs):
        self.order_calls += 1
        raise AssertionError("order_send must never be called by /d1-metadata")


@pytest.fixture
def endpoint(monkeypatch):
    monkeypatch.setenv("REMOTE_MT5_BRIDGE_TOKEN", "synthetic-test-token")
    monkeypatch.delenv("MT5_SYMBOL_MAP", raising=False)
    fake = FakeMT5()
    monkeypatch.setattr(server, "_mt5", lambda: fake)
    return fake


def get(symbol="EURUSD", count=32):
    return server.d1_metadata(symbol=symbol, count=count, _=None)


def test_authentication_required(endpoint):
    with pytest.raises(HTTPException) as caught:
        server._require_auth(None)
    assert caught.value.status_code == 401


def test_demo_account_required_and_live_rejected(endpoint, monkeypatch):
    live = FakeMT5(trade_mode=2)
    monkeypatch.setattr(server, "_mt5", lambda: live)
    with pytest.raises(HTTPException) as caught:
        get()
    assert caught.value.status_code == 403
    assert live.copy_calls == []
    assert live.order_calls == 0


def test_missing_demo_account_rejected(endpoint, monkeypatch):
    fake = FakeMT5()
    fake.account_info = lambda: None
    monkeypatch.setattr(server, "_mt5", lambda: fake)
    with pytest.raises(HTTPException) as caught:
        get()
    assert caught.value.status_code == 503
    assert fake.copy_calls == []
    assert fake.order_calls == 0


def test_symbol_must_be_in_frozen_mapping(endpoint):
    fake = endpoint
    with pytest.raises(HTTPException) as caught:
        get(symbol="USDCAD")
    assert caught.value.status_code == 400
    assert "frozen V3 mapping" in caught.value.detail
    assert fake.copy_calls == []


@pytest.mark.parametrize("provider", ["EURUSD.a", "EURUSDm", "mEURUSD"])
def test_prefixes_and_suffixes_rejected(endpoint, monkeypatch, provider):
    fake = endpoint
    monkeypatch.setenv("MT5_SYMBOL_MAP", '{"EURUSD":"' + provider + '"}')
    with pytest.raises(HTTPException) as caught:
        get()
    assert caught.value.status_code == 400
    assert "prefixes/suffixes" in caught.value.detail
    assert fake.copy_calls == []


@pytest.mark.parametrize("count", [0, 1, 401, 1000])
def test_count_outside_frozen_bounds_rejected(endpoint, count):
    fake = endpoint
    with pytest.raises(HTTPException) as caught:
        get(count=count)
    assert caught.value.status_code == 400
    assert fake.copy_calls == []


def test_insufficient_bars_rejected(endpoint, monkeypatch):
    fake = FakeMT5(rates=[{"time": 1785276000}])
    monkeypatch.setattr(server, "_mt5", lambda: fake)
    with pytest.raises(HTTPException) as caught:
        get()
    assert caught.value.status_code == 404
    assert fake.order_calls == 0


def test_response_is_sorted_unique_timestamp_only_and_sanitized(endpoint):
    fake = endpoint
    body = get()
    timestamps = body["bar_open_timestamps"]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))
    assert body["timeframe"] == "D1"
    assert body["ohlc_included"] is False
    assert body["company"] == "MetaQuotes Ltd."
    assert body["server"] == "MetaQuotes-Demo"
    assert body["provider_symbol"] == "EURUSD"
    assert body["bridge_version"] == "2026.07.29-d1-metadata.1"
    assert not {"open", "high", "low", "close"} & set(body)
    serialized = str(body).lower()
    for forbidden in ("login", "balance", "equity", "password"):
        assert forbidden not in serialized
    assert fake.copy_calls == [("EURUSD", fake.TIMEFRAME_D1, 0, 32)]
    assert fake.order_calls == 0


def test_duplicate_timestamps_rejected(endpoint, monkeypatch):
    fake = FakeMT5(rates=[
        {"time": 1785276000},
        {"time": 1785276000},
    ])
    monkeypatch.setattr(server, "_mt5", lambda: fake)
    with pytest.raises(HTTPException) as caught:
        get()
    assert caught.value.status_code == 502
    assert fake.order_calls == 0


def test_health_exposes_sanitized_d1_metadata_build_version(endpoint):
    assert server.health()["bridge_version"] == "2026.07.29-d1-metadata.1"
