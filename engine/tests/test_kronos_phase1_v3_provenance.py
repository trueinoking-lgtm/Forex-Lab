from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.kronos_v3_provenance import (
    EXPLORATORY_ROOT,
    POINT_BASELINES,
    PROSPECTIVE_ROOT,
    ProvenanceError,
    authorize_final_attempt,
    canonical_manifest_hash,
    select_point_baseline,
    validate_batch_chain,
    validate_evidence_eligibility,
    validate_evidence_root,
    validate_final_interval,
    validate_frozen_hashes,
    validate_minimum_accrual,
    validate_safety,
    validate_source,
    validate_stage_data_access,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads(
    (ROOT / "engine/docs/kronos_phase1_v3_config.json").read_text()
)
CONTAMINATION = json.loads(
    (ROOT / "docs/kronos_phase1_v3_contamination_ledger.json").read_text()
)


def test_v2_cannot_be_labelled_preregistered():
    status = (ROOT / "docs/kronos_phase1_v3_status.md").read_text()
    assert "POST-RESULT EXPLORATORY GATES — NOT A VALID PREREGISTRATION" in status
    assert "V2 gates" in status


@pytest.mark.parametrize(
    "metadata",
    [
        {"version": "V2", "evidence_eligible": True},
        {"run_id": "phase1-20260725T152651Z", "evidence_eligible": True},
        {"is_synthetic": True, "evidence_eligible": True},
    ],
)
def test_run_a_v2_and_synthetic_cannot_satisfy_v3(metadata):
    with pytest.raises(ProvenanceError):
        validate_evidence_eligibility(metadata)


def test_final_interval_begins_after_freeze_and_contamination():
    validate_final_interval(
        "2026-08-01T12:00:00+00:00",
        "2026-08-03T00:00:00+00:00",
        "2028-08-01T00:00:00+00:00",
        CONTAMINATION["final_contamination_cutoffs"],
    )
    with pytest.raises(ProvenanceError, match="strictly after freeze"):
        validate_final_interval(
            "2026-08-03T00:00:00+00:00",
            "2026-08-03T00:00:00+00:00",
            "2028-08-01T00:00:00+00:00",
            CONTAMINATION["final_contamination_cutoffs"],
        )


def test_target_dates_cannot_overlap_contamination():
    with pytest.raises(ProvenanceError, match="overlaps contamination"):
        validate_final_interval(
            "2009-01-01T00:00:00+00:00",
            "2010-02-01T20:30:00+00:00",
            "2011-01-01T00:00:00+00:00",
            CONTAMINATION["final_contamination_cutoffs"],
        )


def test_unapproved_pair_source_server_or_timeframe_fails():
    approved = {
        "broker_company": "Approved Co",
        "broker_server": "Approved-Server",
        "timeframe": "D1",
        "pairs": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"],
        "symbol_mappings": {"EURUSD": "EURUSD"},
    }
    for field, value in (
        ("broker_company", "Other"),
        ("broker_server", "Other"),
        ("timeframe", "H1"),
        ("pairs", ["EURUSD"]),
        ("symbol_mappings", {"EURUSD": "EURUSD.a"}),
    ):
        actual = dict(approved)
        actual[field] = value
        with pytest.raises(ProvenanceError):
            validate_source(actual, approved)


@pytest.mark.parametrize("stage", ["development", "validation"])
def test_prospective_data_cannot_be_opened_early(stage):
    with pytest.raises(ProvenanceError):
        validate_stage_data_access(stage, [f"{PROSPECTIVE_ROOT}/batch.csv"])


def test_final_inference_refused_before_minimum_accrual():
    with pytest.raises(ProvenanceError, match="minimum accrual"):
        validate_minimum_accrual({pair: 99 for pair in CONFIG["dataset"]["pairs"]})
    validate_minimum_accrual({pair: 100 for pair in CONFIG["dataset"]["pairs"]})


@pytest.mark.parametrize("changed", ["protocol", "code", "config", "model", "tokenizer"])
def test_post_freeze_changes_invalidate_study(changed):
    frozen = {name: f"{name}-hash" for name in ("protocol", "code", "config", "model", "tokenizer")}
    actual = dict(frozen)
    actual[changed] = "changed"
    with pytest.raises(ProvenanceError, match=changed):
        validate_frozen_hashes(frozen, actual)


def test_point_baselines_exclude_stochastic_random_walk():
    assert POINT_BASELINES == ("last_value", "drift", "rolling_mean_20", "ema_20")
    assert "random_walk" not in CONFIG["point_baselines"]
    assert CONFIG["random_walk"]["point_baseline_eligible"] is False


def test_point_baseline_selected_on_development_only_with_frozen_tie_order():
    tied = {name: 1.0 for name in POINT_BASELINES}
    assert select_point_baseline("development", tied) == "last_value"
    with pytest.raises(ProvenanceError):
        select_point_baseline("development", {**tied, "random_walk": 0.0})


@pytest.mark.parametrize("stage", ["validation", "final_test"])
def test_validation_and_final_cannot_reselect_baseline(stage):
    assert select_point_baseline(stage, {}, previously_selected="drift") == "drift"
    with pytest.raises(ProvenanceError):
        select_point_baseline(stage, {}, previously_selected=None)


def test_final_execution_counter_permits_only_one_attempt():
    assert authorize_final_attempt([], CONFIG["study_id"]) == 1
    with pytest.raises(ProvenanceError, match="already contains"):
        authorize_final_attempt(
            [{"study_id": CONFIG["study_id"], "attempt_number": 1}],
            CONFIG["study_id"],
        )


def test_evidence_roots_cannot_cross_link():
    validate_evidence_root("prospective", f"{PROSPECTIVE_ROOT}/study")
    validate_evidence_root("exploratory", f"{EXPLORATORY_ROOT}/study")
    with pytest.raises(ProvenanceError):
        validate_evidence_root("prospective", f"{EXPLORATORY_ROOT}/study")


def test_live_order_capability_automatically_disqualifies():
    validate_safety(CONFIG["safety"])
    unsafe = dict(CONFIG["safety"], ALLOW_LIVE_ORDERS=True)
    with pytest.raises(ProvenanceError, match="live-order"):
        validate_safety(unsafe)


def test_immutable_acquisition_batch_hash_chain():
    manifest = {
        "acquisition_timestamp": "2030-01-02T00:00:00+00:00",
        "first_bar_timestamp": "2030-01-01T00:00:00+00:00",
        "last_bar_timestamp": "2030-01-01T00:00:00+00:00",
        "row_count": 1,
        "source_identity": "synthetic-fixture",
        "file_sha256": "0" * 64,
        "previous_manifest_sha256": None,
    }
    manifest["current_manifest_sha256"] = canonical_manifest_hash(manifest)
    validate_batch_chain(None, manifest)


def test_protocol_has_dynamic_not_backdated_target_rule():
    assert CONFIG["protocol_freeze_commit"] == "SELF"
    assert CONFIG["protocol_freeze_timestamp"] == "COMMITTER_TIMESTAMP"
    assert CONFIG["first_authorised_test_target"].startswith("FIRST_COMPLETE")
    assert "2026-07-29" not in json.dumps(CONFIG)


def test_source_identity_is_frozen_not_pending():
    dataset = CONFIG["dataset"]
    assert dataset["broker_company"] == "MetaQuotes Ltd."
    assert dataset["broker_server"] == "MetaQuotes-Demo"
    assert dataset["symbol_mappings"] == {pair: pair for pair in dataset["pairs"]}
    assert "PENDING" not in json.dumps(dataset)


def test_execution_authorisations_and_counter_are_inactive():
    assert not any(CONFIG["execution_authorisation"].values())
