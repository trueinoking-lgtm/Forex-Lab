"""New York Fed Markets Data API adapter for EFFR and SOFR."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List

from ..models import Observation, SourceRecord
from .base import BaseSourceAdapter, SourceAcquisitionError

PARSER_VERSION = "1.0.0"


class NewYorkFedAdapter(BaseSourceAdapter):
    """Adapter for NY Fed Markets Data API endpoints."""

    def identify_source(self) -> str:
        return "new_york_fed"

    def build_request(self, source: SourceRecord, start_date: date, end_date: date) -> dict:
        required = ["institution", "official_source_location", "exact_series_identifier",
                     "first_available_date", "latest_available_date"]
        for field in required:
            val = getattr(source, field, None)
            if val is None or val == "":
                raise SourceAcquisitionError(f"NY Fed registry record missing required field: {field}")

        series_id = source.exact_series_identifier
        endpoint_template = source.official_source_location

        return {
            "method": "GET",
            "endpoint": endpoint_template,
            "series_identifier": series_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "params": {"startDate": start_date.isoformat(), "endDate": end_date.isoformat()},
        }

    def acquire_raw(self, request: dict) -> bytes:
        raise SourceAcquisitionError(
            "NY Fed Markets Data API acquisition not yet implemented. "
            "Registry record is valid; awaiting acquisition implementation."
        )

    def parse_raw(self, raw: bytes, source: SourceRecord) -> List[Observation]:
        raise SourceAcquisitionError("No raw data acquired yet; cannot parse.")

    def normalise_observations(self, observations: List[Observation]) -> List[Observation]:
        return observations

    def validate_source_response(self, raw: bytes, source: SourceRecord) -> bool:
        return False
