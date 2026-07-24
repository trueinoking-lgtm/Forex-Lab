"""Tests for FX carry source registry."""
import json
import pytest
from engine.carry_data.source_registry import (
    load_registry,
    get_canonical_sources,
    get_source_by_currency,
    validate_registry,
)
from engine.carry_data.models import SourceRecord


def test_registry_loads():
    records = load_registry()
    assert len(records) > 0, "Registry must have at least one record"


def test_all_records_have_required_fields():
    records = load_registry()
    required = [
        "currency", "benchmark_name", "institution", "official_source_location",
        "exact_series_identifier", "benchmark_type", "secured_or_unsecured",
        "frequency", "observation_timezone", "value_date_semantics",
        "publication_time", "publication_lag", "first_available_date",
        "latest_available_date", "revision_policy", "methodology_changes",
        "holiday_handling", "missing_value_policy", "machine_readable_format",
        "access_requirements", "licensing_or_redistribution_restrictions",
        "intended_research_role", "known_limitations",
    ]
    for i, rec in enumerate(records):
        for field in required:
            assert hasattr(rec, field), f"Record {i} ({rec.benchmark_name}) missing field {field}"
            val = getattr(rec, field, None)
            assert val is not None and val != "", f"Record {i} ({rec.benchmark_name}) has empty field {field}"


def test_canonical_excludes_policy_rates():
    canonical = get_canonical_sources()
    for rec in canonical:
        assert rec.benchmark_type not in ("policy_rate_weekly", "policy_rate_daily"), \
            f"Policy rate {rec.benchmark_name} must not be in canonical sources"


def test_canonical_excludes_mirrors():
    canonical = get_canonical_sources()
    for rec in canonical:
        assert rec.provider != "Federal Reserve Bank of St. Louis / FRED", \
            f"FRED mirror {rec.benchmark_name} must not be canonical"


def test_canonical_excludes_bbsw():
    canonical = get_canonical_sources()
    bbsw = [r for r in canonical if "BBSW" in r.benchmark_name]
    assert len(bbsw) == 0, "BBSW must not be in canonical carry panel"


def test_aud_split_has_both_records():
    aud = get_source_by_currency("AUD")
    aonia = [r for r in aud if "AONIA" in r.benchmark_name or "RBA cash" in r.benchmark_name]
    bbsw = [r for r in aud if "BBSW" in r.benchmark_name]
    cash = [r for r in aud if "Cash Rate" in r.benchmark_name]
    assert len(aonia) >= 1, "AUD must have an AONIA record"
    assert len(bbsw) >= 1, "AUD must have a BBSW record"


def test_eur_three_regimes():
    eur = get_source_by_currency("EUR")
    overnight = [r for r in eur if r.benchmark_type not in ("policy_rate_weekly",)]
    regimes = {r.methodology_regime or r.benchmark_name for r in overnight}
    assert any(
        ("EONIA_original" in (r.methodology_regime or "")) or "EONIA (original" in r.benchmark_name
        for r in overnight
    ), "EUR must have original EONIA regime record"
    assert any("ESTR" in (r.methodology_regime or "") or "short-period" in r.benchmark_name.lower() or "€str" in r.benchmark_name.lower() or "euro" in r.benchmark_name.lower() for r in overnight), \
        "EUR must have euro_short-term_rate regime record"
    assert any("recalibrated" in (r.methodology_regime or "").lower() for r in overnight), \
        "EUR must have recalibrated EONIA regime record"


def test_usd_ffd_is_mirror_not_canonical():
    usd = get_source_by_currency("USD")
    fred = [r for r in usd if "FRED" in (r.provider or "") or "FEDFUNDS" in r.exact_series_identifier]
    for r in fred:
        assert "secondary" in (r.intended_research_role or "").lower(), f"FRED mirror must be labelled secondary/diagnostic in intended_research_role, got: {r.intended_research_role}"


def test_duplicate_benchmark_names():
    records = load_registry()
    names = [r.benchmark_name for r in records]
    seen = set()
    dupes = []
    for n in names:
        if n in seen:
            dupes.append(n)
        seen.add(n)
    assert len(dupes) == 0, f"Duplicate benchmark names found: {dupes}"


def test_fred_only_in_mirror_role():
    records = load_registry()
    fred_records = [r for r in records if "FRED" in (r.provider or "")]
    for r in fred_records:
        assert "mirror" in (r.role or "").lower() or "secondary" in (r.role or "").lower(), \
            f"FRED record must be labelled as mirror/secondary, got role: {r.role}"
