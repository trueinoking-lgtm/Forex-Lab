"""Acceptance tests for the five-currency BIS policy-rate change-point panel."""
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

POLICY_CSV = Path("engine/data/fx_carry/policy_proxy/five_currency_policy_rate_change_points.csv")
POLICY_MANIFEST = POLICY_CSV.with_suffix(".manifest.json")
FINANCING_CSV = Path("engine/data/fx_carry/canonical/currency_financing_rates_daily.csv")
EXPECTED = {"USD", "EUR", "GBP", "JPY", "AUD"}

# BIS verified latest daily date (confirmed 2026-07-24)
BIS_LATEST_VERIFIED_DATE = "2026-07-21"


def rows():
    with POLICY_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_panel_file_exists():
    """The canonical sparse change-point CSV must exist."""
    assert POLICY_CSV.exists(), f"Panel CSV not found: {POLICY_CSV}"


def test_manifest_file_exists():
    """The corresponding manifest must exist."""
    assert POLICY_MANIFEST.exists(), f"Manifest not found: {POLICY_MANIFEST}"


def test_raw_artifact_preserved():
    """Raw artifact must exist on disk with verifiable SHA-256."""
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    raw = manifest.get("raw_artifact", {})
    artifact_path = raw.get("path")
    assert artifact_path and Path(artifact_path).exists(), (
        "raw_artifact_path must point to a stored file on disk"
    )
    actual_sha = hashlib.sha256(Path(artifact_path).read_bytes()).hexdigest()
    assert actual_sha == manifest.get("raw_sha256"), (
        f"raw_sha256 mismatch: manifest={manifest.get('raw_sha256')} actual={actual_sha}"
    )


def test_five_currencies_present():
    """Panel must contain all five currencies."""
    data = rows()
    assert {r["currency"] for r in data} == EXPECTED
    for currency in EXPECTED:
        dates = [r["observation_date"] for r in data if r["currency"] == currency]
        assert min(dates) == "2010-01-01"
        assert max(dates) <= BIS_LATEST_VERIFIED_DATE, (
            f"Latest {currency} observation {max(dates)} exceeds BIS latest {BIS_LATEST_VERIFIED_DATE}"
        )


def test_panel_separation():
    """Policy change-point panel must never be in currency_financing panel."""
    assert POLICY_CSV.resolve() != FINANCING_CSV.resolve()
    if FINANCING_CSV.exists():
        assert "POLICY_RATE_CHANGE_POINTS" not in FINANCING_CSV.read_text(
            encoding="utf-8"
        ), "Policy change-point panel must never appear in currency financing panel"


def test_panel_type_not_proxy_label():
    """panel_type must be POLICY_RATE_CHANGE_POINTS, never POLICY_RATE_PROXY or overnight benchmark."""
    for row in rows():
        assert row["panel_type"] == "POLICY_RATE_CHANGE_POINTS", (
            f"Wrong panel_type: {row['panel_type']}"
        )


def test_policy_rates_not_overnight_benchmarks():
    """No row may be labelled as an overnight benchmark."""
    for row in rows():
        assert "overnight" not in row["policy_rate_type"].lower()
        assert row["policy_rate_percent"]


def test_source_row_identifier_present():
    """Every row must carry a source_row_identifier linking back to the source."""
    for row in rows():
        assert row.get("source_row_identifier"), (
            f"Missing source_row_identifier for {row['observation_date']} {row['currency']}"
        )


def test_sparse_not_daily():
    """Sparse policy-change observations must not be labelled as daily frequency."""
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    freq = manifest.get("frequency", "")
    assert freq != "D", (
        "Sparse change-point product must not be labelled frequency='D' (daily). "
        "Use 'sparse-change-point' or equivalent."
    )
    assert "change" in freq.lower() or "sparse" in freq.lower(), (
        f"frequency label '{freq}' should indicate sparse/change-point nature"
    )


def test_no_future_observations():
    """No observation may exceed the latest verifiable BIS release date."""
    data = rows()
    for row in data:
        assert row["observation_date"] <= BIS_LATEST_VERIFIED_DATE, (
            f"Observation {row['observation_date']} for {row['currency']} exceeds "
            f"latest verifiable BIS date {BIS_LATEST_VERIFIED_DATE}"
        )


def test_publication_aware_availability():
    """Publication timestamp must account for BIS release timing."""
    for row in rows():
        observed = datetime.fromisoformat(row["observation_date"])
        published = datetime.fromisoformat(
            row["publication_timestamp_utc"]
        ).replace(tzinfo=None)
        available = datetime.fromisoformat(
            row["data_available_timestamp_utc"]
        ).replace(tzinfo=None)
        acquired = datetime.fromisoformat(
            row["acquisition_timestamp_utc"]
        ).replace(tzinfo=None)
        assert row["publication_timestamp_method"] == "CONSERVATIVE_RELEASE_RULE_DERIVED"
        assert observed <= published <= available <= acquired


def test_no_duplicate_currency_date_regime_keys():
    """Sparse change-point keys (currency, observation_date, methodology_regime) must be unique."""
    data = rows()
    keys = [
        (r["currency"], r["observation_date"], r["methodology_regime"]) for r in data
    ]
    assert len(keys) == len(
        set(keys)
    ), f"Duplicate currency/date/regime keys found in {len(keys)} rows"


def test_manifest_raw_hash_matches_stored_artifact():
    """manifest raw_sha256 must match the actual stored raw file on disk."""
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    raw = manifest.get("raw_artifact", {})
    artifact_path = Path(raw.get("path", ""))
    assert artifact_path.exists(), (
        f"raw_artifact does not exist on disk: {artifact_path}"
    )
    actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert manifest["raw_sha256"] == actual, (
        f"raw_sha256 mismatch: manifest claims {manifest['raw_sha256']} "
        f"but stored file hashes to {actual}"
    )


def test_no_mirrors_silently_substituted():
    """No FRED or mirror substitution allowed."""
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["mirror_substitution"] is False
    for row in rows():
        assert "FRED" not in "|".join(row.values()).upper()


def test_quarantine_directory_exists():
    """Unverified original panel must be preserved in quarantine, not deleted."""
    quarantine = Path(
        "engine/data/fx_carry/policy_proxy/quarantine/unverified_20260724T165924Z"
    )
    assert quarantine.exists(), (
        "Original unverified panel must be preserved in quarantine directory"
    )
    csv_in_quarantine = quarantine / "five_currency_policy_rates_daily.csv"
    assert csv_in_quarantine.exists(), (
        "Quarantine directory must contain original CSV"
    )
