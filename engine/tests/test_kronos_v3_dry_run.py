from __future__ import annotations

import hashlib
import json

import pytest

from engine.kronos_v3_acquisition.bridge import BridgeRequestError
from engine.kronos_v3_acquisition.collector import (
    APPROVED_PAIRS,
    D1Bar,
    SourceIdentity,
)
from engine.tools.kronos_v3_acquisition_dry_run import execute_metadata_audit

NOW = "2026-07-29T09:34:53+00:00"
SECRET_URL = "http://private-bridge.invalid:8787"
SECRET_TOKEN = "synthetic-secret-token-never-record"


class FakeClient:
    def __init__(
        self,
        *,
        health_error=None,
        company="MetaQuotes Ltd.",
        server="MetaQuotes-Demo",
        provider_overrides=None,
        bars_by_pair=None,
    ):
        self.last_http_status = None
        self.health_error = health_error
        self.company = company
        self.server = server
        self.provider_overrides = provider_overrides or {}
        self.bars_by_pair = bars_by_pair or {
            pair: [
                "2026-07-24T00:00:00+00:00",
                "2026-07-27T00:00:00+00:00",
                "2026-07-28T00:00:00+00:00",
                "2026-07-29T00:00:00+00:00",
            ]
            for pair in APPROVED_PAIRS
        }
        self.calls = []

    def health(self):
        self.calls.append(("GET", "/health"))
        if self.health_error:
            raise self.health_error
        self.last_http_status = 200
        return {
            "ok": True,
            "broker_mode": "demo",
            "bridge_version": "2026.07.29-d1-metadata.1",
        }

    def d1_metadata(self, symbol):
        self.calls.append(("GET", "/d1-metadata", symbol))
        source = SourceIdentity(
            broker_company=self.company,
            broker_server=self.server,
            symbol=symbol,
            provider_symbol=self.provider_overrides.get(symbol, symbol),
            timeframe="D1",
            broker_mode="demo",
        )
        return source, [D1Bar.metadata(value) for value in self.bars_by_pair[symbol]]

    def account(self):
        raise AssertionError("account endpoint must not be called")

    def symbols(self):
        raise AssertionError("symbols endpoint must not be called")

    def place_order(self):
        raise AssertionError("order endpoint must not be called")


def serialized(evidence):
    return json.dumps(evidence, sort_keys=True)


def test_url_token_and_their_hashes_are_absent_from_evidence():
    evidence, status = execute_metadata_audit(FakeClient(), NOW)
    text = serialized(evidence)
    assert status == 0
    assert SECRET_URL not in text
    assert SECRET_TOKEN not in text
    assert hashlib.sha256(SECRET_URL.encode()).hexdigest() not in text
    assert hashlib.sha256(SECRET_TOKEN.encode()).hexdigest() not in text
    assert "bridge_url" not in text
    assert "token_hash" not in text


def test_timeout_classification_is_connectivity_failed():
    client = FakeClient(health_error=BridgeRequestError(
        "BRIDGE_CONNECTIVITY_FAILED", "/health"
    ))
    evidence, status = execute_metadata_audit(client, NOW)
    assert status == 2
    assert evidence["result"] == "BRIDGE_CONNECTIVITY_FAILED"
    assert evidence["bridge_contact_attempted"] is True
    assert evidence["health_response_received"] is False
    assert evidence["failure_stage"] == "/health"


def test_http_401_classification_is_authentication_failed():
    client = FakeClient(health_error=BridgeRequestError(
        "BRIDGE_AUTHENTICATION_FAILED", "/health", 401
    ))
    evidence, status = execute_metadata_audit(client, NOW)
    assert status == 2
    assert evidence["result"] == "BRIDGE_AUTHENTICATION_FAILED"
    assert evidence["health_http_status"] == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"company": "Other Broker"},
        {"server": "Other-Server"},
        {"provider_overrides": {"EURUSD": "EURUSDm"}},
    ],
)
def test_source_identity_mismatch_classification(changes):
    evidence, status = execute_metadata_audit(FakeClient(**changes), NOW)
    assert status == 3
    assert evidence["result"] == "SOURCE_IDENTITY_MISMATCH"
    assert evidence["failure_stage"] == "pair_source_identity"


def test_four_pair_calendar_mismatch_classification():
    client = FakeClient()
    client.bars_by_pair["AUDUSD"] = [
        "2026-07-24T00:00:00+00:00",
        "2026-07-27T00:00:00+00:00",
        "2026-07-28T00:00:00+00:00",
        "2026-07-30T00:00:00+00:00",
    ]
    evidence, status = execute_metadata_audit(client, NOW)
    assert status == 4
    assert evidence["result"] == "FOUR_PAIR_CALENDAR_MISMATCH"


def test_valid_null_target_is_success():
    client = FakeClient()
    evidence, status = execute_metadata_audit(client, NOW)
    assert status == 0
    assert evidence["result"] == "METADATA_BOUNDARY_VERIFIED_NO_TARGET_ELIGIBLE"
    common = evidence["common_calendar_audit"]
    assert common["first_possible_target_strictly_after_conservative_start"] == (
        "2026-07-30T00:00:00+00:00"
    )
    assert common["proposed_first_eligible_target"] is None
    assert evidence["health_response_received"] is True
    assert evidence["health_http_status"] == 200


def test_no_ohlc_inference_baseline_metric_or_order_path_is_invoked():
    client = FakeClient()
    evidence, status = execute_metadata_audit(client, NOW)
    assert status == 0
    assert client.calls == [
        ("GET", "/health"),
        ("GET", "/d1-metadata", "EURUSD"),
        ("GET", "/d1-metadata", "GBPUSD"),
        ("GET", "/d1-metadata", "USDJPY"),
        ("GET", "/d1-metadata", "AUDUSD"),
    ]
    assert evidence["real_ohlc_persisted"] is False
    assert evidence["inference_executed"] is False
    assert evidence["baseline_calculated"] is False
    assert evidence["metrics_calculated"] is False
    assert evidence["orders_placed_or_simulated"] is False
