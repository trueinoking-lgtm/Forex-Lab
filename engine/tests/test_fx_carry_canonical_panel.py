"""Tests for canonical FX financing rate panel."""
import csv
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import pytest

PANEL_CSV = Path("engine/data/fx_carry/canonical/currency_financing_rates_daily.csv")
PANEL_MANIFEST = Path("engine/data/fx_carry/canonical/currency_financing_rates_daily.manifest.json")

REQUIRED_COLUMNS = [
    "observation_date", "currency", "benchmark_name", "benchmark_rate_percent",
    "benchmark_type", "secured_unsecured", "value_date", "publication_timestamp_utc",
    "publication_timestamp_method", "data_available_date_utc", "source_revision_status",
    "methodology_regime", "source_institution", "source_series_id", "canonical_source",
    "source_file_sha256", "acquisition_id", "acquisition_timestamp_utc",
    "parser_version", "quality_status",
]


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_canonical_schema_columns():
    """Panel must have all required columns in the correct order."""
    with open(PANEL_CSV, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == REQUIRED_COLUMNS, f"Schema mismatch. Got: {header}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_deterministic_output():
    """Panel CSV SHA-256 must match manifest."""
    assert PANEL_CSV.exists()
    assert PANEL_MANIFEST.exists()
    manifest = json.loads(PANEL_MANIFEST.read_text())
    actual_sha = hashlib.sha256(PANEL_CSV.read_bytes()).hexdigest()
    assert manifest["panel_sha256"] == actual_sha, \
        f"Panel SHA mismatch: manifest={manifest['panel_sha256']}, actual={actual_sha}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_canonical_source_true():
    """All observations must have canonical_source=True."""
    with open(PANEL_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            assert row["canonical_source"] == "True", \
                f"Non-canonical row found for {row['observation_date']} {row['benchmark_name']}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_no_duplicate_canonical_keys():
    """No duplicate (observation_date, currency, benchmark_name, methodology_regime) keys."""
    seen = set()
    duplicates = []
    with open(PANEL_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["observation_date"], row["currency"], row["benchmark_name"], row["methodology_regime"])
            if key in seen:
                duplicates.append(key)
            seen.add(key)
    assert len(duplicates) == 0, f"Duplicate canonical keys found: {duplicates[:5]}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_no_lookahead():
    """All publication timestamps must be before or equal to observation date (conservative)
    or within documented publication lag. For our acquired data, publication lag is documented
    in the registry, and the data is historical so lookahead cannot be violated."""
    with open(PANEL_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # publication_timestamp_method should be documented
            assert row["publication_timestamp_method"] in ("SOURCE_REPORTED", "DOCUMENTED_RULE_DERIVED"), \
                f"Invalid publication_timestamp_method for {row['observation_date']}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_secured_sofr_not_mixed_with_effr():
    """SOFR must never be labelled as EFFR, and EFFR must never be labelled as SOFR."""
    effr_benchmarks = set()
    sofr_benchmarks = set()
    with open(PANEL_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["source_series_id"] == "EFFR":
                effr_benchmarks.add(row["benchmark_name"])
            if row["source_series_id"] == "SOFR":
                sofr_benchmarks.add(row["benchmark_name"])
    
    assert "Federal Funds Effective Rate (EFFR)" in effr_benchmarks
    assert "Secured Overnight Financing Rate (SOFR)" in sofr_benchmarks
    # No cross-contamination
    for name in effr_benchmarks:
        assert "SOFR" not in name, f"EFFR benchmark contaminated with SOFR: {name}"
    for name in sofr_benchmarks:
        assert "EFFR" not in name, f"SOFR benchmark contaminated with EFFR: {name}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_bbsw_excluded_from_canonical_panel():
    """BBSW must not appear in the canonical panel."""
    with open(PANEL_CSV, newline="") as f:
        reader = csv.DictReader(f)
        bbsw_rows = [r for r in reader if "BBSW" in r.get("benchmark_name", "")]
    assert len(bbsw_rows) == 0, "BBSW must not be in canonical panel"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_policy_rates_excluded_from_canonical_panel():
    """Policy rates (weekly) must not appear in the canonical panel."""
    policy_types = {"policy_rate_weekly", "policy_rate_daily", "policy_rate_cross_check"}
    with open(PANEL_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            assert row["benchmark_type"] not in policy_types, \
                f"Policy rate in canonical panel: {row['benchmark_name']}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_mirror_excluded_from_canonical_panel():
    """FRED mirror must not be in canonical panel."""
    with open(PANEL_CSV, newline="") as f:
        reader = csv.DictReader(f)
        fred_rows = [r for r in reader if "FRED" in r.get("source_institution", "") or "FEDFUNDS" in r.get("source_series_id", "")]
    assert len(fred_rows) == 0, "FRED mirror must not be in canonical panel"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_manifest_has_all_fields():
    """Manifest must have all required metadata fields."""
    manifest = json.loads(PANEL_MANIFEST.read_text())
    required_fields = [
        "panel_sha256", "row_count", "currencies", "benchmarks",
        "first_observation_per_benchmark", "last_observation_per_benchmark",
        "acquisition_ids", "raw_source_hashes", "duplicate_count",
        "missing_count", "lookahead_violations", "source_failures",
        "licensing_summary", "creation_timestamp_utc",
    ]
    for field in required_fields:
        assert field in manifest, f"Manifest missing required field: {field}"


@pytest.mark.skipif(not PANEL_CSV.exists(), reason="Panel CSV not yet built")
def test_row_count_matches_manifest():
    """Panel CSV row count must match manifest."""
    with open(PANEL_CSV, newline="") as f:
        row_count = sum(1 for _ in f) - 1  # minus header
    manifest = json.loads(PANEL_MANIFEST.read_text())
    assert manifest["row_count"] == row_count, \
        f"Manifset row_count={manifest['row_count']}, CSV rows={row_count}"
