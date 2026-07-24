"""Tests for FX carry availability and lookahead guard."""
import pytest
from datetime import datetime, timezone, timedelta


def test_get_available_rates_returns_list():
    """get_available_rates must return a list."""
    from engine.carry_data.availability import get_available_rates
    from engine.carry_data.models import Observation
    now = datetime.now(timezone.utc)
    obs = Observation(
        observation_date=datetime.now(timezone.utc).date(),
        currency="USD", benchmark_name="EFFR", benchmark_rate_percent=0.12,
        benchmark_type="overnight_unsecured", secured_unsecured="unsecured",
        value_date=datetime.now(timezone.utc).date(),
        publication_timestamp_utc=now - timedelta(hours=1),
        publication_timestamp_method="SOURCE_REPORTED",
        data_available_date_utc=datetime.now(timezone.utc).date(),
        source_revision_status="current", methodology_regime="EFFR",
        source_institution="Federal Reserve Bank of New York",
        source_series_id="EFFR", canonical_source=True,
        source_file_sha256="abc", acquisition_id="test",
        acquisition_timestamp_utc=now, parser_version="1.0.0",
        quality_status="valid",
    )
    result = get_available_rates([obs], now)
    assert isinstance(result, list)


def test_get_available_rates_filters_future_publications():
    """Observations with publication timestamps in the future (relative to
    decision_timestamp_utc) must be excluded."""
    from engine.carry_data.availability import get_available_rates
    from engine.carry_data.models import Observation
    decision = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
    obs = Observation(
        observation_date=datetime.now(timezone.utc).date(),
        currency="USD", benchmark_name="EFFR", benchmark_rate_percent=0.12,
        benchmark_type="overnight_unsecured", secured_unsecured="unsecured",
        value_date=datetime.now(timezone.utc).date(),
        publication_timestamp_utc=decision + timedelta(hours=1),  # future
        publication_timestamp_method="SOURCE_REPORTED",
        data_available_date_utc=datetime.now(timezone.utc).date(),
        source_revision_status="current", methodology_regime="EFFR",
        source_institution="Federal Reserve Bank of New York",
        source_series_id="EFFR", canonical_source=True,
        source_file_sha256="abc", acquisition_id="test",
        acquisition_timestamp_utc=decision, parser_version="1.0.0",
        quality_status="valid",
    )
    result = get_available_rates([obs], decision)
    assert len(result) == 0, "Future publication must be excluded"


def test_get_available_rates_includes_past_publications():
    """Observations with publication timestamps before the decision timestamp
    must be included."""
    from engine.carry_data.availability import get_available_rates
    from engine.carry_data.models import Observation
    decision = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
    obs = Observation(
        observation_date=datetime.now(timezone.utc).date(),
        currency="USD", benchmark_name="EFFR", benchmark_rate_percent=0.12,
        benchmark_type="overnight_unsecured", secured_unsecured="unsecured",
        value_date=datetime.now(timezone.utc).date(),
        publication_timestamp_utc=decision - timedelta(hours=1),  # past
        publication_timestamp_method="SOURCE_REPORTED",
        data_available_date_utc=datetime.now(timezone.utc).date(),
        source_revision_status="current", methodology_regime="EFFR",
        source_institution="Federal Reserve Bank of New York",
        source_series_id="EFFR", canonical_source=True,
        source_file_sha256="abc", acquisition_id="test",
        acquisition_timestamp_utc=decision, parser_version="1.0.0",
        quality_status="valid",
    )
    result = get_available_rates([obs], decision)
    assert len(result) == 1, "Past publication must be included"


def test_check_lookahead_violations_returns_list():
    """check_lookahead_violations must return a list of violations."""
    from engine.carry_data.lookahead_guard import check_lookahead_violations
    from engine.carry_data.models import Observation
    decision = datetime.now(timezone.utc)
    result = check_lookahead_violations([], decision)
    assert isinstance(result, list)
