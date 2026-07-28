"""Pure-stdlib, no-model provenance guards for Kronos Phase 1 V3."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

POINT_BASELINES = ("last_value", "drift", "rolling_mean_20", "ema_20")
PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
PROSPECTIVE_ROOT = "engine/evidence/kronos/v3/prospective"
EXPLORATORY_ROOT = "engine/evidence/kronos/v3/exploratory"


class ProvenanceError(ValueError):
    """Fail-closed provenance violation."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_final_interval(
    freeze_timestamp: str,
    first_target: str,
    last_target: str,
    cutoffs: Mapping[str, str],
) -> None:
    freeze = parse_timestamp(freeze_timestamp)
    first = parse_timestamp(first_target)
    last = parse_timestamp(last_target)
    if first <= freeze:
        raise ProvenanceError("first authorised test target must be strictly after freeze")
    if last < first:
        raise ProvenanceError("last authorised test target precedes first target")
    for pair in PAIRS:
        if first <= parse_timestamp(cutoffs[pair]):
            raise ProvenanceError(f"{pair}: final target interval overlaps contamination")


def validate_source(
    actual: Mapping[str, Any], approved: Mapping[str, Any]
) -> None:
    for field in ("broker_company", "broker_server", "timeframe"):
        if actual.get(field) != approved.get(field):
            raise ProvenanceError(f"unapproved source field: {field}")
    if actual.get("pairs") != approved.get("pairs"):
        raise ProvenanceError("unapproved pair set")
    if actual.get("symbol_mappings") != approved.get("symbol_mappings"):
        raise ProvenanceError("unapproved symbol mapping")


def validate_evidence_eligibility(metadata: Mapping[str, Any]) -> None:
    if metadata.get("version") == "V2" or metadata.get("run_id", "").startswith(
        "phase1-20260725"
    ):
        raise ProvenanceError("V2 and Run A evidence are ineligible for V3")
    if metadata.get("is_synthetic"):
        raise ProvenanceError("synthetic evidence is ineligible for V3")
    if metadata.get("evidence_eligible") is not True:
        raise ProvenanceError("evidence is not explicitly eligible")


def validate_stage_data_access(stage: str, paths: Iterable[str]) -> None:
    if stage in {"development", "validation"}:
        for path in paths:
            if path == PROSPECTIVE_ROOT or path.startswith(PROSPECTIVE_ROOT + "/"):
                raise ProvenanceError(f"{stage} cannot open prospective data")


def validate_minimum_accrual(
    complete_origins_by_pair: Mapping[str, int], minimum: int = 100
) -> None:
    for pair in PAIRS:
        if complete_origins_by_pair.get(pair, 0) < minimum:
            raise ProvenanceError(f"{pair}: minimum accrual not reached")


def validate_frozen_hashes(
    authorised: Mapping[str, str], actual: Mapping[str, str]
) -> None:
    required = ("protocol", "code", "config", "model", "tokenizer")
    for name in required:
        if not authorised.get(name) or actual.get(name) != authorised.get(name):
            raise ProvenanceError(f"post-freeze {name} identity mismatch")


def select_point_baseline(
    stage: str, scores: Mapping[str, float], previously_selected: str | None = None
) -> str:
    if stage != "development":
        if previously_selected not in POINT_BASELINES:
            raise ProvenanceError("validation/final must reuse the development baseline")
        return previously_selected
    if set(scores) != set(POINT_BASELINES):
        raise ProvenanceError("point baseline set must exclude stochastic random walk")
    return min(POINT_BASELINES, key=lambda name: (scores[name], POINT_BASELINES.index(name)))


def authorize_final_attempt(
    records: Sequence[Mapping[str, Any]], study_id: str
) -> int:
    attempts = [
        int(record["attempt_number"])
        for record in records
        if record.get("study_id") == study_id
    ]
    if attempts:
        raise ProvenanceError("final execution counter already contains an attempt")
    return 1


def validate_evidence_root(classification: str, path: str) -> None:
    expected = PROSPECTIVE_ROOT if classification == "prospective" else EXPLORATORY_ROOT
    other = EXPLORATORY_ROOT if classification == "prospective" else PROSPECTIVE_ROOT
    if not (path == expected or path.startswith(expected + "/")) or path.startswith(other):
        raise ProvenanceError("exploratory and prospective evidence roots cannot cross-link")


def validate_safety(config: Mapping[str, Any]) -> None:
    if config.get("paper_only") is not True:
        raise ProvenanceError("paper_only must be true")
    if config.get("ALLOW_LIVE_ORDERS") is not False:
        raise ProvenanceError("live-order capability automatically disqualifies V3")
    for field in ("order_placement", "watcher_activation", "signal_forcing"):
        if config.get(field) is not False:
            raise ProvenanceError(f"{field} must be false")


def canonical_manifest_hash(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("current_manifest_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_batch_chain(
    previous_manifest: Mapping[str, Any] | None,
    current_manifest: Mapping[str, Any],
) -> None:
    required = {
        "acquisition_timestamp",
        "first_bar_timestamp",
        "last_bar_timestamp",
        "row_count",
        "source_identity",
        "file_sha256",
        "previous_manifest_sha256",
        "current_manifest_sha256",
    }
    if not required <= current_manifest.keys():
        raise ProvenanceError("incomplete acquisition batch manifest")
    expected_previous = (
        previous_manifest["current_manifest_sha256"] if previous_manifest else None
    )
    if current_manifest["previous_manifest_sha256"] != expected_previous:
        raise ProvenanceError("broken acquisition manifest hash chain")
    if current_manifest["current_manifest_sha256"] != canonical_manifest_hash(
        current_manifest
    ):
        raise ProvenanceError("incorrect current acquisition manifest hash")
