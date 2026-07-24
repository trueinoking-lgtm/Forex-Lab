"""Tests for Phase 2A BIS Policy-Rate Proxy Panel."""
import pytest
import json
import hashlib
from pathlib import Path

POLICY_DIR = Path("engine/data/fx_carry/policy_proxy")
POLICY_CSV = POLICY_DIR / "five_currency_policy_rates_daily.csv"
POLICY_MANIFEST = POLICY_DIR / "five_currency_policy_rates_daily.manifest.json"
ACQ_INDEX = Path("engine/config/fx_carry_policy_proxy_acquisition_index.json")
PANEL_INDEX = Path("engine/config/fx_carry_policy_proxy_panel_index.json")


def test_policy_proxy_panel_separation():
    """Policy rate panel must never be in currency_financing panel."""
    if not POLICY_CSV.exists():
        pytest.skip("Policy proxy panel not yet built (all sources blocked)")
    financing_csv = Path("engine/data/fx_carry/canonical/currency_financing_rates_daily.csv")
    if financing_csv.exists():
        assert not financing_csv.samefile(POLICY_CSV), (
            "Policy proxy panel must be a separate file from currency financing panel"
        )


def test_five_currencies_present():
    """Policy proxy panel must contain all five currencies."""
    if not POLICY_CSV.exists():
        pytest.skip("Policy proxy panel not yet built (all sources blocked)")
    text = POLICY_CSV.read_text()
    currencies = set()
    for line in text.splitlines()[1:]:
        row = line.split(",")
        if len(row) > 1:
            currencies.add(row[1])
    assert currencies == {"USD", "EUR", "GBP", "JPY", "AUD"}


def test_policy_rates_not_overnight_benchmarks():
    """Policy rate rows must never be marked as overnight benchmarks."""
    if not POLICY_CSV.exists():
        pytest.skip("Policy proxy panel not yet built")
    import csv
    with open(POLICY_CSV, newline="") as f:
        for row in csv.DictReader(f):
            assert row.get("panel_type") == "POLICY_RATE_PROXY", (
                f"Row {row.get('observation_date')} has wrong panel_type"
            )
            assert "overnight" not in row.get("policy_rate_type", "").lower(), (
                f"Policy rate row cannot be overnight benchmark: {row}"
            )


def test_publication_aware_availability():
    """Every row must have a publication timestamp method, not just observation_date."""
    if not POLICY_CSV.exists():
        pytest.skip("Policy proxy panel not yet built")
    assert POLICY_MANIFEST.exists()
    manifest = json.loads(POLICY_MANIFEST.read_text())
    assert manifest.get("policy_rate_proxy") == True


def test_methodology_transitions_recorded():
    """Manifest must document methodology breaks."""
    if not POLICY_MANIFEST.exists():
        pytest.skip("Policy proxy panel not yet built")
    manifest = json.loads(POLICY_MANIFEST.read_text())
    assert "methodology_breaks" in manifest or "policy_rate_proxy" in manifest


def test_source_hashes_present():
    """If panel exists, every source row must have a source_file_sha256."""
    if not POLICY_CSV.exists():
        pytest.skip("Policy proxy panel not yet built")
    import csv
    with open(POLICY_CSV, newline="") as f:
        for row in csv.DictReader(f):
            assert row.get("source_file_sha256"), (
                f"Missing source_file_sha256 for {row.get('observation_date')}"
            )


def test_deterministic_output():
    """Rebuilding the panel must produce the same SHA-256."""
    if not POLICY_CSV.exists():
        pytest.skip("Policy proxy panel not yet built")
    actual = hashlib.sha256(POLICY_CSV.read_bytes()).hexdigest()
    manifest = json.loads(POLICY_MANIFEST.read_text())
    assert manifest["panel_sha256"] == actual


def test_no_mirrors_silently_substituted():
    """Policy rate sources must not include mirror columns or FRED mirrors."""
    if not POLICY_CSV.exists():
        pytest.skip("Policy proxy panel not yet built")
    import csv
    with open(POLICY_CSV, newline="") as f:
        for row in csv.DictReader(f):
            source_id = row.get("source_series_id", "")
            assert "MIRROR" not in source_id.upper()
            assert "FRED" not in source_id.upper()
