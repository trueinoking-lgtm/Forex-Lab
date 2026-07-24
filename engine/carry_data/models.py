"""Data models for FX carry acquisition framework."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class SourceRecord:
    currency: str
    benchmark_name: str
    institution: str
    official_source_location: str
    exact_series_identifier: str
    benchmark_type: str
    secured_or_unsecured: str
    frequency: str
    observation_timezone: str
    value_date_semantics: str
    publication_time: str
    publication_lag: str
    first_available_date: str
    latest_available_date: str
    revision_policy: str
    methodology_changes: str
    holiday_handling: str
    missing_value_policy: str
    machine_readable_format: str
    access_requirements: str
    licensing_or_redistribution_restrictions: str
    intended_research_role: str
    known_limitations: str
    provider: Optional[str] = None
    role: Optional[str] = None
    methodology_regime: Optional[str] = None


@dataclass
class Observation:
    observation_date: date
    currency: str
    benchmark_name: str
    benchmark_rate_percent: float
    benchmark_type: str
    secured_unsecured: str
    value_date: date
    publication_timestamp_utc: datetime
    publication_timestamp_method: str
    data_available_date_utc: date
    source_revision_status: str
    methodology_regime: str
    source_institution: str
    source_series_id: str
    canonical_source: bool
    source_file_sha256: str
    acquisition_id: str
    acquisition_timestamp_utc: datetime
    parser_version: str
    quality_status: str


@dataclass
class AcquisitionManifest:
    acquisition_id: str
    source_uri: str
    response_sha256: str
    request_metadata: dict
    acquisition_timestamp_utc: datetime
    http_status: int
    content_type: str
    source_identifier: str
    requested_date_range: tuple
    parser_version: str
    licensing_metadata: str
    source_registry_version_hash: str
    raw_response_path: str


CANONICAL_PANEL_COLUMNS = [
    "observation_date", "currency", "benchmark_name", "benchmark_rate_percent",
    "benchmark_type", "secured_unsecured", "value_date", "publication_timestamp_utc",
    "publication_timestamp_method", "data_available_date_utc", "source_revision_status",
    "methodology_regime", "source_institution", "source_series_id", "canonical_source",
    "source_file_sha256", "acquisition_id", "acquisition_timestamp_utc", "parser_version",
    "quality_status",
]
