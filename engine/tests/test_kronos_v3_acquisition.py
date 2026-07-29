from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from engine.kronos_v3_acquisition.collector import (
    AcquisitionError,
    D1Bar,
    FrozenAcquisitionPolicy,
    ImmutableBatchStore,
    SourceIdentity,
    audit_common_calendar,
    audit_symbol,
)

ROOT = Path(__file__).resolve().parents[2]
RECEIPT_SHA = "57a1345050d71ee66b1be63378feccd05bed52ad2a3fae6b4be3e9be067ea114"


def source(symbol="EURUSD", **changes):
    values = {
        "broker_company": "MetaQuotes Ltd.",
        "broker_server": "MetaQuotes-Demo",
        "symbol": symbol,
        "provider_symbol": symbol,
        "timeframe": "D1",
        "broker_mode": "demo",
    }
    values.update(changes)
    return SourceIdentity(**values)


def metadata_bars():
    return [
        D1Bar.metadata("2026-07-28T21:00:00+00:00"),
        D1Bar.metadata("2026-07-29T21:00:00+00:00"),
        D1Bar.metadata("2026-07-30T21:00:00+00:00"),
        D1Bar.metadata("2026-07-31T21:00:00+00:00"),
    ]


def real_bar(timestamp, close="1.1"):
    close_value = Decimal(close)
    return D1Bar(
        timestamp=datetime.fromisoformat(timestamp),
        open=close_value,
        high=close_value + Decimal("0.01"),
        low=close_value - Decimal("0.01"),
        close=close_value,
    )


def test_exact_source_identity_passes():
    result = audit_symbol(
        source(), metadata_bars(), "2026-08-02T22:00:00+00:00"
    )
    assert result["proposed_first_eligible_target"] == "2026-07-28T21:00:00+00:00"
    assert result["latest_bar_is_still_forming"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"broker_company": "Wrong Broker"},
        {"broker_server": "Wrong-Server"},
        {"provider_symbol": "EURUSD.a"},
        {"provider_symbol": "EURUSDm"},
        {"timeframe": "H1"},
        {"broker_mode": "live"},
    ],
)
def test_wrong_source_identity_fails_closed(changes):
    with pytest.raises(AcquisitionError, match="source identity mismatch"):
        audit_symbol(
            source(**changes), metadata_bars(), "2026-08-02T22:00:00+00:00"
        )


def test_incomplete_latest_d1_bar_is_rejected_as_target():
    result = audit_symbol(
        source(), metadata_bars(), "2026-08-02T22:00:00+00:00"
    )
    assert result["latest_available_d1_bar_timestamp"] == "2026-07-31T21:00:00+00:00"
    assert result["proposed_first_eligible_target"] != result[
        "latest_available_d1_bar_timestamp"
    ]


def test_pre_freeze_bar_is_rejected():
    bars = [
        D1Bar.metadata("2026-07-27T21:00:00+00:00"),
        D1Bar.metadata("2026-07-28T00:00:00+00:00"),
        D1Bar.metadata("2026-07-29T21:00:00+00:00"),
        D1Bar.metadata("2026-07-30T21:00:00+00:00"),
    ]
    result = audit_symbol(source(), bars, "2026-08-02T22:00:00+00:00")
    assert result["proposed_first_eligible_target"] == "2026-07-29T21:00:00+00:00"


def test_acquisition_delay_violation_is_rejected():
    result = audit_symbol(
        source(), metadata_bars(), "2026-07-30T20:59:59+00:00"
    )
    assert result["proposed_first_eligible_target"] is None


def test_valid_post_freeze_complete_bar_passes():
    result = audit_symbol(
        source(), metadata_bars(), "2026-07-30T21:00:00+00:00"
    )
    assert result["proposed_first_eligible_target"] == "2026-07-28T21:00:00+00:00"


def test_mixed_pair_calendars_are_recorded_honestly():
    audits = {
        pair: audit_symbol(
            source(pair), metadata_bars(), "2026-08-02T22:00:00+00:00"
        )
        for pair in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
    }
    audits["AUDUSD"] = dict(audits["AUDUSD"])
    audits["AUDUSD"]["latest_available_d1_bar_timestamp"] = (
        "2026-08-03T21:00:00+00:00"
    )
    result = audit_common_calendar(audits)
    assert result["mixed_pair_calendars"] is True
    assert result["latest_common_calendar"] is False


def test_acquisition_inactive_refuses_all_writes(tmp_path):
    store = ImmutableBatchStore(tmp_path, FrozenAcquisitionPolicy(active=False))
    with pytest.raises(AcquisitionError, match="inactive"):
        store.write(
            source(),
            [real_bar("2026-07-29T21:00:00+00:00"),
             real_bar("2026-07-30T21:00:00+00:00")],
            "2026-08-02T22:00:00+00:00",
            RECEIPT_SHA,
            "a" * 40,
        )
    assert list(tmp_path.rglob("*")) == []


def test_duplicate_batch_and_overwrite_are_rejected(tmp_path):
    store = ImmutableBatchStore(tmp_path, FrozenAcquisitionPolicy(active=True))
    args = (
        source(),
        [real_bar("2026-07-29T21:00:00+00:00"),
         real_bar("2026-07-30T21:00:00+00:00")],
        "2026-08-02T22:00:00+00:00",
        RECEIPT_SHA,
        "a" * 40,
    )
    store.write(*args)
    with pytest.raises(AcquisitionError, match="duplicate batch|overwrite"):
        store.write(*args)


def test_broken_previous_manifest_hash_fails(tmp_path):
    previous = tmp_path / "previous.manifest.json"
    previous.write_text(json.dumps({
        "previous_manifest_sha256": None,
        "current_manifest_sha256": "0" * 64,
    }))
    store = ImmutableBatchStore(tmp_path / "batches", FrozenAcquisitionPolicy(active=True))
    with pytest.raises(AcquisitionError, match="broken previous"):
        store.write(
            source(),
            [real_bar("2026-07-29T21:00:00+00:00"),
             real_bar("2026-07-30T21:00:00+00:00")],
            "2026-08-02T22:00:00+00:00",
            RECEIPT_SHA,
            "a" * 40,
            previous,
        )


def test_altered_raw_csv_fails_manifest_verification(tmp_path):
    store = ImmutableBatchStore(tmp_path, FrozenAcquisitionPolicy(active=True))
    raw, manifest = store.write(
        source(),
        [real_bar("2026-07-29T21:00:00+00:00"),
         real_bar("2026-07-30T21:00:00+00:00")],
        "2026-08-02T22:00:00+00:00",
        RECEIPT_SHA,
        "a" * 40,
    )
    payload = json.loads(manifest.read_text())
    raw.chmod(0o644)
    raw.write_bytes(raw.read_bytes() + b"altered")
    assert hashlib.sha256(raw.read_bytes()).hexdigest() != payload["raw_file_sha256"]


def test_serialization_is_frozen_and_has_no_volume(tmp_path):
    store = ImmutableBatchStore(tmp_path, FrozenAcquisitionPolicy(active=True))
    raw, _ = store.write(
        source(),
        [real_bar("2026-07-29T21:00:00+00:00") ,
         real_bar("2026-07-30T21:00:00+00:00")],
        "2026-08-02T22:00:00+00:00",
        RECEIPT_SHA,
        "a" * 40,
    )
    data = raw.read_bytes()
    assert data.startswith(b"timestamp,open,high,low,close\n")
    assert b"\r\n" not in data
    assert b"volume" not in data and b"amount" not in data


def test_fresh_subprocess_import_and_synthetic_audit_are_model_free():
    code = """
import sys
assert 'torch' not in sys.modules
assert 'transformers' not in sys.modules
import engine.kronos_v3_acquisition.collector as c
assert 'torch' not in sys.modules
assert 'transformers' not in sys.modules
assert not any(name.lower().startswith('kronos') for name in sys.modules)
s = c.SourceIdentity('MetaQuotes Ltd.', 'MetaQuotes-Demo', 'EURUSD', 'EURUSD', 'D1', 'demo')
b = [c.D1Bar.metadata('2026-07-29T21:00:00+00:00'), c.D1Bar.metadata('2026-07-30T21:00:00+00:00')]
c.audit_symbol(s, b, '2026-08-01T21:00:00+00:00')
assert 'torch' not in sys.modules
assert 'transformers' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", (
            "import sys; sys.path.insert(0, " + repr(str(ROOT)) + ");" + code
        )],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_collector_source_has_no_inference_metric_or_order_imports():
    package = ROOT / "engine/kronos_v3_acquisition"
    text = "\n".join(path.read_text() for path in package.glob("*.py"))
    forbidden = (
        "import torch", "import transformers", "kronos_adapter",
        "run_phase1", "import engine.baseline", "import engine.metrics",
        "place_demo_order",
    )
    for token in forbidden:
        assert token not in text


def test_live_orders_and_final_counter_cannot_be_activated():
    config = json.loads(
        (ROOT / "engine/docs/kronos_phase1_v3_config.json").read_text()
    )
    policy = json.loads(
        (ROOT / "engine/docs/manifests/kronos_phase1_v3_data_acquisition_policy.json").read_text()
    )
    assert policy["active"] is False
    assert config["safety"]["ALLOW_LIVE_ORDERS"] is False
    assert config["safety"]["order_placement"] is False
    assert config["execution_authorisation"]["data_acquisition"] is False
    assert config["execution_authorisation"]["final_execution_counter_active"] is False
