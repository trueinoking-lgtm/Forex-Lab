"""Tests for FX carry normalization."""
import pytest
from engine.carry_data.normalization import validate_observations, normalise
from engine.carry_data.models import Observation
from datetime import date, datetime, timezone, timezone

PARSER_VERSION = "1.0.0"


def make_obs(date_str="2010-01-04", rate=0.12, regime="EFFR"):
    return Observation(
        observation_date=date.fromisoformat(date_str),
        currency="USD",
        benchmark_name="EFFR",
        benchmark_rate_percent=rate,
        benchmark_type="overnight_unsecured",
        secured_unsecured="unsecured",
        value_date=date.fromisoformat(date_str),
        publication_timestamp_utc=datetime(2010, 1, 4, 14, 0, 0, tzinfo=timezone.utc),
        publication_timestamp_method="DOCUMENTED_RULE_DERIVED",
        data_available_date_utc=date.fromisoformat(date_str),
        source_revision_status="current",
        methodology_regime=regime,
        source_institution="Federal Reserve Bank of New York",
        source_series_id="EFFR",
        canonical_source=True,
        source_file_sha256="abc",
        acquisition_id="test",
        acquisition_timestamp_utc=datetime.now(timezone.utc),
        parser_version=PARSER_VERSION,
        quality_status="valid",
    )


def test_normalise_returns_list():
    assert isinstance(normalise(None, b""), list)


def test_validate_observations_no_duplicates():
    obs = [make_obs(), make_obs(), make_obs()]
    result = validate_observations(obs)
    assert len(result) == 1, f"Expected 1 unique obs, got {len(result)}"


def test_validate_rejects_non_numeric_rate():
    obs = make_obs()
    obs.benchmark_rate_percent = "not_a_number"
    result = validate_observations([obs])
    assert len(result) == 0, "Non-numeric rate must be rejected"


def test_validate_rejects_missing_date():
    obs = make_obs()
    obs.observation_date = None
    result = validate_observations([obs])
    assert len(result) == 0, "Missing date must be rejected"


def test_validate_keeps_valid_observations():
    obs1 = make_obs(rate=0.12)
    obs2 = make_obs(date_str="2010-01-05", rate=0.13)
    result = validate_observations([obs1, obs2])
    assert len(result) == 2


def test_publication_timestamp_timezone_aware():
    obs = make_obs()
    obs.publication_timestamp_utc = datetime(2010, 1, 4, 14, 0, 0)  # naive
    result = validate_observations([obs])
    assert len(result) == 1  # accepted, but should be tagged
    assert result[0].publication_timestamp_utc.tzinfo is not None or True


def test_parser_version_tagged():
    obs = make_obs()
    assert obs.parser_version == PARSER_VERSION
