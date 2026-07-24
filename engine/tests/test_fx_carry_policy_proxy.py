"""Acceptance tests for the five-currency BIS policy-rate proxy panel."""
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

POLICY_CSV = Path("engine/data/fx_carry/policy_proxy/five_currency_policy_rates_daily.csv")
POLICY_MANIFEST = POLICY_CSV.with_suffix(".manifest.json")
FINANCING_CSV = Path("engine/data/fx_carry/canonical/currency_financing_rates_daily.csv")
EXPECTED = {"USD", "EUR", "GBP", "JPY", "AUD"}


def rows():
    with POLICY_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_five_currencies_present():
    data = rows()
    assert {r["currency"] for r in data} == EXPECTED
    for currency in EXPECTED:
        dates = [r["observation_date"] for r in data if r["currency"] == currency]
        assert min(dates) == "2010-01-01"
        assert max(dates) >= "2026-07-23"


def test_panel_separation():
    assert POLICY_CSV.resolve() != FINANCING_CSV.resolve()
    if FINANCING_CSV.exists():
        assert "POLICY_RATE_PROXY" not in FINANCING_CSV.read_text(encoding="utf-8")


def test_policy_rates_not_overnight_benchmarks():
    for row in rows():
        assert row["panel_type"] == "POLICY_RATE_PROXY"
        assert "overnight" not in row["policy_rate_type"].lower()
        assert row["policy_rate_percent"]


def test_publication_aware_availability():
    for row in rows():
        observed = datetime.fromisoformat(row["observation_date"])
        published = datetime.fromisoformat(row["publication_timestamp_utc"]).replace(tzinfo=None)
        available = datetime.fromisoformat(row["data_available_timestamp_utc"]).replace(tzinfo=None)
        acquired = datetime.fromisoformat(row["acquisition_timestamp_utc"]).replace(tzinfo=None)
        assert row["publication_timestamp_method"] == "CONSERVATIVE_RELEASE_RULE_DERIVED"
        assert observed <= published <= available <= acquired


def test_methodology_transitions_recorded():
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["methodology_breaks"]
    recorded = {(item["currency"], item["effective_date"]) for item in manifest["methodology_breaks"]}
    assert ("JPY", "2016-02-16") in recorded
    assert ("JPY", "2024-03-19") in recorded
    assert len({r["methodology_regime"] for r in rows() if r["currency"] == "JPY"}) >= 3


def test_source_hashes_present():
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    assert len(manifest["raw_sha256"]) == 64
    assert manifest["raw_sha256"] in manifest["raw_source_hashes"]
    assert manifest["registry_hash"]
    assert all(r["source_file_sha256"] == manifest["raw_sha256"] for r in rows())


def test_deterministic_output():
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    assert hashlib.sha256(POLICY_CSV.read_bytes()).hexdigest() == manifest["panel_sha256"]
    keys = [
        (r["observation_date"], r["currency"], r["methodology_regime"])
        for r in rows()
    ]
    assert len(keys) == len(set(keys))


def test_no_mirrors_silently_substituted():
    manifest = json.loads(POLICY_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["mirror_substitution"] is False
    assert manifest["bis_dataset_identifier"] == "BIS,WS_CBPOL,1.0"
    assert manifest["request_metadata"]["url"].startswith("https://data.bis.org/")
    for row in rows():
        assert row["source_series_id"].startswith("BIS,WS_CBPOL,1.0/")
        assert "FRED" not in "|".join(row.values()).upper()
