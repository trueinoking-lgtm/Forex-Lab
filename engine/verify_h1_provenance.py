#!/usr/bin/env python3
"""Verify the canonical MT5 H1 provenance closeout artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from src.timestamp_validation import guard_session_dependent_strategy


SYMBOLS = ("EURUSD", "AUDUSD", "GBPUSD", "USDJPY")
ENGINE_DIR = Path(__file__).resolve().parent
DATA_DIR = ENGINE_DIR / "data"
EXPECTED_TIMESTAMP_FIELDS: dict[str, Any] = {
    "timestamp_semantics": "BROKER_SERVER_BAR_OPEN_TIME",
    "timestamp_timezone_label_original": "UTC_INCORRECT",
    "historical_offset_policy": "UNRESOLVED",
    "timestamp_research_restrictions": "exact_session_mapping_not_authorised",
    "observed_server_offset_at_probe": "+03:00",
    "observed_offset_seconds": 10800,
    "probe_timestamp_utc": "2026-07-24",
    "timezone_probe_file": "mt5_time_probe_output.json",
}


def sha256_file(path: Path) -> str:
    """Return a file's SHA-256 without modifying or loading it all at once."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_manifest_path(symbol: str) -> Path:
    """Resolve only the canonical, top-level manifest for a supported symbol."""
    if symbol not in SYMBOLS:
        raise ValueError(f"unsupported symbol: {symbol}")
    return DATA_DIR / f"raw_mt5_{symbol}_1h.manifest.json"


def load_canonical_manifest(symbol: str) -> tuple[Path, dict[str, Any]]:
    """Load one explicitly named canonical manifest; never search archives."""
    path = canonical_manifest_path(symbol)
    if not path.is_file():
        raise FileNotFoundError(f"canonical manifest not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest root is not an object: {path}")
    return path, manifest


def verify_symbol(symbol: str) -> list[str]:
    """Verify provenance metadata, CSV hash, and the session guard."""
    evidence: list[str] = []
    manifest_path, manifest = load_canonical_manifest(symbol)
    evidence.append(
        f"{symbol} MANIFEST: PASS "
        f"({manifest_path.relative_to(ENGINE_DIR).as_posix()})"
    )

    if "csv_sha256" in manifest:
        raise ValueError(
            f"{symbol}: forbidden csv_sha256 field present; file_sha256 must be preserved"
        )

    for field, expected in EXPECTED_TIMESTAMP_FIELDS.items():
        actual = manifest.get(field)
        if actual != expected or type(actual) is not type(expected):
            raise ValueError(
                f"{symbol}: {field} expected {expected!r}, got {actual!r}"
            )
    evidence.append(f"{symbol} TIMESTAMP METADATA: PASS")

    probe_path = DATA_DIR / manifest["timezone_probe_file"]
    if not probe_path.is_file() or probe_path.parent != DATA_DIR:
        raise FileNotFoundError(f"{symbol}: canonical timezone probe not found")
    evidence.append(
        f"{symbol} TIMEZONE PROBE: PASS ({probe_path.name})"
    )

    csv_path = DATA_DIR / f"raw_mt5_{symbol}_1h.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"{symbol}: CSV not found: {csv_path}")
    expected_hash = manifest.get("file_sha256")
    if not isinstance(expected_hash, str):
        raise ValueError(f"{symbol}: file_sha256 is missing or is not a string")
    actual_hash = sha256_file(csv_path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"{symbol}: CSV SHA256 mismatch: "
            f"manifest={expected_hash} actual={actual_hash}"
        )
    evidence.append(f"{symbol} CSV SHA256: PASS {actual_hash}")

    try:
        guard_session_dependent_strategy(DATA_DIR, symbol, "1h")
    except ValueError:
        evidence.append(f"{symbol} SESSION GUARD: PASS (blocked)")
    else:
        raise ValueError(f"{symbol}: session-dependent strategy was not blocked")

    return evidence


def main() -> int:
    """Run all checks and provide literal closeout evidence on stdout."""
    print("H1 PROVENANCE VERIFICATION")
    print(f"DATA DIRECTORY: {DATA_DIR}")
    print(
        "CANONICAL DISCOVERY: explicit top-level manifests only; "
        "archive/temp files not searched"
    )

    failures: list[str] = []
    for symbol in SYMBOLS:
        try:
            for line in verify_symbol(symbol):
                print(line)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(str(exc))
            print(f"{symbol} VERIFICATION: FAIL ({exc})")

    print("TEMP CLEANUP: PASS (no temporary files created)")
    if failures:
        print(f"RESULT: FAIL ({len(failures)} error(s))")
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    print("RESULT: PASS (4/4 canonical H1 datasets verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
