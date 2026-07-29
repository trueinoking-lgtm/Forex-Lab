#!/usr/bin/env python3
"""Sanitized metadata-only V3 dry run; never writes prospective market rows."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.kronos_v3_acquisition.bridge import (
    BridgeRequestError,
    MetadataBridgeClient,
)
from engine.kronos_v3_acquisition.collector import (  # noqa: E402
    APPROVED_PAIRS,
    AcquisitionError,
    FrozenAcquisitionPolicy,
    audit_common_calendar,
    audit_symbol,
)


def _base_evidence(now: str) -> dict[str, object]:
    return {
        "$schema": "kronos-phase1-v3-real-bridge-metadata-dry-run",
        "executed_at": now,
        "execution_mode": "read_only_metadata_dry_run",
        "bridge_contact_attempted": False,
        "health_response_received": False,
        "health_http_status": None,
        "bridge_version": None,
        "broker_mode": None,
        "failure_stage": None,
        "real_ohlc_persisted": False,
        "prospective_batch_written": False,
        "inference_executed": False,
        "metrics_calculated": False,
        "baseline_calculated": False,
        "orders_placed_or_simulated": False,
        "data_acquisition_active": False,
        "final_test_counter_active": False,
    }


def execute_metadata_audit(client, now: str) -> tuple[dict[str, object], int]:
    evidence = _base_evidence(now)
    try:
        evidence["bridge_contact_attempted"] = True
        health = client.health()
        evidence["health_response_received"] = True
        evidence["health_http_status"] = client.last_http_status
        evidence["bridge_version"] = health.get("bridge_version")
        evidence["broker_mode"] = health.get("broker_mode")
        if (
            health.get("ok") is not True
            or health.get("bridge_version") != "2026.07.29-d1-metadata.1"
            or health.get("broker_mode") != "demo"
        ):
            evidence["failure_stage"] = "health_source_identity"
            evidence["result"] = "SOURCE_IDENTITY_MISMATCH"
            return evidence, 3

        audits = {}
        source_identities = {}
        for symbol in APPROVED_PAIRS:
            source, bars = client.d1_metadata(symbol)
            audits[symbol] = audit_symbol(
                source, bars, now, FrozenAcquisitionPolicy()
            )
            source_identities[symbol] = {
                "company": source.broker_company,
                "server": source.broker_server,
                "broker_mode": source.broker_mode,
                "symbol": source.symbol,
                "provider_symbol": source.provider_symbol,
                "timeframe": source.timeframe,
            }
        common = audit_common_calendar(audits)
        evidence["source_identities"] = source_identities
        evidence["d1_boundary_audit"] = audits
        evidence["common_calendar_audit"] = common
        evidence["proposed_raw_root"] = (
            "engine/evidence/kronos/v3/prospective/raw/<symbol>/"
        )
        evidence["proposed_manifest_root"] = (
            "engine/evidence/kronos/v3/prospective/manifests/<symbol>/"
        )
        if (
            not common["all_four_pairs_same_d1_boundary"]
            or not common["latest_common_calendar"]
            or common["mixed_pair_calendars"]
            or common["first_possible_target_strictly_after_conservative_start"] is None
        ):
            evidence["failure_stage"] = "four_pair_common_calendar"
            evidence["result"] = "FOUR_PAIR_CALENDAR_MISMATCH"
            return evidence, 4
        if common["proposed_first_eligible_target"] is None:
            evidence["result"] = "METADATA_BOUNDARY_VERIFIED_NO_TARGET_ELIGIBLE"
        else:
            evidence["result"] = "METADATA_BOUNDARY_VERIFIED_TARGET_ELIGIBLE"
        return evidence, 0
    except BridgeRequestError as exc:
        evidence["health_http_status"] = exc.http_status
        evidence["failure_stage"] = exc.stage
        evidence["result"] = exc.category
        return evidence, 2
    except AcquisitionError:
        evidence["failure_stage"] = "pair_source_identity"
        evidence["result"] = "SOURCE_IDENTITY_MISMATCH"
        return evidence, 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--now")
    args = parser.parse_args()
    output = Path(args.output)
    now = args.now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    base_url = os.environ.get("REMOTE_MT5_BRIDGE_URL", "")
    token = os.environ.get("REMOTE_MT5_BRIDGE_TOKEN", "")
    if not base_url or not token:
        evidence = _base_evidence(now)
        evidence["failure_stage"] = "configuration"
        evidence["result"] = "BRIDGE_CONNECTIVITY_FAILED"
        status = 2
    else:
        client = MetadataBridgeClient(base_url, token)
        evidence, status = execute_metadata_audit(client, now)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(evidence["result"])
    return status


if __name__ == "__main__":
    raise SystemExit(main())
