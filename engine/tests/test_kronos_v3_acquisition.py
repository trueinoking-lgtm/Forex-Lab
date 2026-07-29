from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from engine.kronos_v3_acquisition.collector import (
    AcquisitionError,
    APPROVED_PAIRS,
    CONSERVATIVE_PROSPECTIVE_START,
    D1Bar,
    FrozenAcquisitionPolicy,
    ImmutableBatchStore,
    PairObservation,
    SignedAcquisitionAuthorization,
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
    assert result["proposed_first_eligible_target"] == "2026-07-29T21:00:00+00:00"
    assert result["first_possible_target_strictly_after_conservative_start"] == (
        "2026-07-29T21:00:00+00:00"
    )
    assert result["latest_bar_is_still_forming"] is True
    assert "No subsequent" in result["latest_bar_status_basis"]


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
        source(), metadata_bars(), "2026-07-31T21:00:00+00:00"
    )
    assert result["proposed_first_eligible_target"] == "2026-07-29T21:00:00+00:00"


def test_audit_preserves_original_offset_and_normalizes_utc():
    bars = [
        D1Bar.metadata("2026-07-30T00:00:00+03:00"),
        D1Bar.metadata("2026-07-31T00:00:00+03:00"),
        D1Bar.metadata("2026-08-01T00:00:00+03:00"),
    ]
    result = audit_symbol(source(), bars, "2026-08-03T00:00:00+00:00")
    assert result["previous_d1_bar_timestamp_original"].endswith("+03:00")
    assert result["previous_d1_bar_timestamp"].endswith("+00:00")
    assert result["broker_server_offsets_inferred_minutes"] == [180]
    assert result["previous_bar_next_open_completeness_proof_original"].endswith(
        "+03:00"
    )


def test_midnight_boundary_first_possible_target_is_not_yet_eligible():
    bars = [
        D1Bar.metadata("2026-07-27T00:00:00+00:00"),
        D1Bar.metadata("2026-07-28T00:00:00+00:00"),
        D1Bar.metadata("2026-07-29T00:00:00+00:00"),
    ]
    result = audit_symbol(source(), bars, "2026-07-29T09:30:00+00:00")
    assert result["first_possible_target_strictly_after_conservative_start"] == (
        "2026-07-30T00:00:00+00:00"
    )
    assert result["first_possible_target_is_observed"] is False
    assert result["proposed_first_eligible_target"] is None


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


def authorisation(signature="synthetic-valid-signature"):
    return SignedAcquisitionAuthorization(
        study_id="kronos-phase1-v3-prospective-replication",
        conservative_start="2026-07-29T09:00:00+00:00",
        authorised_at="2026-08-01T00:00:00+00:00",
        signer="synthetic-test-signer",
        signature=signature,
    )


def observations(timestamp="2026-07-29T21:00:00+00:00",
                 next_open="2026-07-30T21:00:00+00:00"):
    return {
        pair: PairObservation(
            source(pair),
            real_bar(timestamp, close=str(Decimal("1.1") + Decimal(index) / 100)),
            datetime.fromisoformat(next_open),
        )
        for index, pair in enumerate(APPROVED_PAIRS)
    }


def active_store(tmp_path, verifier=lambda payload, signature, signer: True):
    return ImmutableBatchStore(
        tmp_path, FrozenAcquisitionPolicy(active=True), verifier
    )


def write_valid(store, **changes):
    values = {
        "observations": observations(),
        "acquired_at": "2026-08-01T21:00:00+00:00",
        "receipt_sha256": RECEIPT_SHA,
        "collector_commit": "a" * 40,
        "authorization": authorisation(),
    }
    values.update(changes)
    return store.write_common_batch(**values)


def test_single_pair_write_path_cannot_bypass_common_boundary(tmp_path):
    store = active_store(tmp_path)
    with pytest.raises(AcquisitionError, match="single-pair write is prohibited"):
        store.write(source(), [real_bar("2026-07-30T21:00:00+00:00")],
                    "2026-08-01T21:00:00+00:00", RECEIPT_SHA, "a" * 40)


def test_acquisition_inactive_refuses_all_writes(tmp_path):
    store = ImmutableBatchStore(
        tmp_path, FrozenAcquisitionPolicy(active=False),
        lambda payload, signature, signer: True,
    )
    with pytest.raises(AcquisitionError, match="inactive"):
        write_valid(store)
    assert list(tmp_path.rglob("*")) == []


def test_separate_signed_authorisation_is_mandatory(tmp_path):
    store = active_store(tmp_path, verifier=lambda payload, signature, signer: False)
    with pytest.raises(AcquisitionError, match="authorisation is invalid"):
        write_valid(store)


def test_target_must_be_strictly_after_conservative_start(tmp_path):
    store = active_store(tmp_path)
    with pytest.raises(AcquisitionError, match="strictly after"):
        write_valid(store, observations=observations(
            "2026-07-29T09:00:00+00:00", "2026-07-30T09:00:00+00:00"
        ))


def test_next_open_and_delay_are_enforced_at_write_boundary(tmp_path):
    store = active_store(tmp_path)
    with pytest.raises(AcquisitionError, match="next-open"):
        write_valid(store, observations=observations(
            next_open="2026-07-29T20:00:00+00:00"
        ))
    with pytest.raises(AcquisitionError, match="24-hour"):
        write_valid(
            store,
            acquired_at="2026-07-31T20:59:59+00:00",
        )


def test_exactly_four_common_timestamp_observations_are_required(tmp_path):
    store = active_store(tmp_path)
    missing = observations()
    missing.pop("AUDUSD")
    with pytest.raises(AcquisitionError, match="all four"):
        write_valid(store, observations=missing)
    mixed = observations()
    mixed["AUDUSD"] = PairObservation(
        source("AUDUSD"),
        real_bar("2026-07-30T21:00:00+00:00"),
        datetime.fromisoformat("2026-07-31T21:00:00+00:00"),
    )
    with pytest.raises(AcquisitionError, match="share one target"):
        write_valid(store, observations=mixed)


def test_all_four_sources_are_validated_at_write_boundary(tmp_path):
    store = active_store(tmp_path)
    bad = observations()
    bad["USDJPY"] = PairObservation(
        source("USDJPY", provider_symbol="USDJPYm"),
        bad["USDJPY"].target,
        bad["USDJPY"].next_open,
    )
    with pytest.raises(AcquisitionError, match="source identity mismatch"):
        write_valid(store, observations=bad)


def test_common_batch_is_atomic_hash_linked_and_non_overwriting(tmp_path):
    store = active_store(tmp_path)
    batch, manifest = write_valid(store)
    assert sorted(path.name for path in batch.iterdir()) == [
        "AUDUSD.csv", "EURUSD.csv", "GBPUSD.csv", "USDJPY.csv",
        "common_batch.manifest.json",
    ]
    payload = json.loads(manifest.read_text())
    assert set(payload["raw_files"]) == set(APPROVED_PAIRS)
    for pair, identity in payload["raw_files"].items():
        data = (batch / identity["relative_path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == identity["sha256"]
    with pytest.raises(AcquisitionError, match="previously recorded|overwrite"):
        write_valid(store)


def test_no_partial_success_when_one_file_write_fails(tmp_path, monkeypatch):
    store = active_store(tmp_path)
    original = store._exclusive_write
    calls = 0

    def fail_third(path, data):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic write failure")
        original(path, data)

    monkeypatch.setattr(store, "_exclusive_write", fail_third)
    with pytest.raises(OSError, match="synthetic"):
        write_valid(store)
    assert not any(path.name.startswith("2026") for path in tmp_path.iterdir())
    assert not any(path.name.startswith(".") for path in tmp_path.iterdir())


def test_broken_previous_manifest_hash_fails(tmp_path):
    previous = tmp_path / "previous.manifest.json"
    previous.write_text(json.dumps({
        "previous_manifest_sha256": None,
        "current_manifest_sha256": "0" * 64,
    }))
    store = active_store(tmp_path / "batches")
    with pytest.raises(AcquisitionError, match="broken previous"):
        write_valid(store, previous_manifest=previous)


def test_serialization_is_frozen_and_has_no_volume(tmp_path):
    store = active_store(tmp_path)
    batch, _ = write_valid(store)
    raw = batch / "EURUSD.csv"
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
