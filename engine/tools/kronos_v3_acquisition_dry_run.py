#!/usr/bin/env python3
"""Sanitized metadata-only V3 dry run; never writes prospective market rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.kronos_v3_acquisition.bridge import MetadataBridgeClient
from engine.kronos_v3_acquisition.collector import (  # noqa: E402
    APPROVED_PAIRS,
    AcquisitionError,
    FrozenAcquisitionPolicy,
    audit_common_calendar,
    audit_symbol,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--now")
    args = parser.parse_args()
    output = Path(args.output)
    now = args.now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    base_url = os.environ.get("REMOTE_MT5_BRIDGE_URL", "")
    token = os.environ.get("REMOTE_MT5_BRIDGE_TOKEN", "")
    evidence: dict[str, object] = {
        "$schema": "kronos-phase1-v3-real-bridge-metadata-dry-run",
        "executed_at": now,
        "execution_mode": "read_only_metadata_dry_run",
        "real_ohlc_persisted": False,
        "prospective_batch_written": False,
        "inference_executed": False,
        "metrics_calculated": False,
        "baseline_calculated": False,
        "orders_placed_or_simulated": False,
        "data_acquisition_active": False,
        "final_test_counter_active": False,
        "bridge_url_sha256": (
            hashlib.sha256(base_url.encode()).hexdigest() if base_url else None
        ),
    }
    status = 0
    try:
        if not base_url or not token:
            raise AcquisitionError("bridge URL/token are not configured")
        client = MetadataBridgeClient(base_url, token)
        evidence["bridge_health"] = client.health()
        account = client.account()
        evidence["account"] = account
        mapping = client.symbols()
        evidence["symbol_mappings"] = mapping
        audits = {}
        for symbol in APPROVED_PAIRS:
            source, bars = client.d1_metadata(symbol)
            audits[symbol] = audit_symbol(
                source, bars, now, FrozenAcquisitionPolicy()
            )
        evidence["d1_boundary_audit"] = audits
        evidence["common_calendar_audit"] = audit_common_calendar(audits)
        evidence["proposed_raw_root"] = (
            "engine/evidence/kronos/v3/prospective/raw/<symbol>/"
        )
        evidence["proposed_manifest_root"] = (
            "engine/evidence/kronos/v3/prospective/manifests/<symbol>/"
        )
        evidence["result"] = "METADATA_DRY_RUN_COMPLETE"
    except AcquisitionError as exc:
        evidence["result"] = "D1_TARGET_BOUNDARY_UNRESOLVED"
        evidence["error"] = str(exc)
        status = 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(evidence["result"])
    return status


if __name__ == "__main__":
    raise SystemExit(main())
