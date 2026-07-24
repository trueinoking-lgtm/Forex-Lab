"""ECB Statistical Data Warehouse adapter for EONIA and euro_short-term_rate."""
from __future__ import annotations
from datetime import date, datetime
from typing import List
from ..models import Observation, SourceRecord
from .base import BaseSourceAdapter, SourceAcquisitionError
PARSER_VERSION = "1.0.0"

class EcbAdapter(BaseSourceAdapter):
    def identify_source(self) -> str: return "ecb"
    def build_request(self, source, start_date, end_date):
        for f in ["institution","official_source_location","exact_series_identifier","first_available_date","latest_available_date"]:
            if not getattr(source, f, None): raise SourceAcquisitionError(f"ECB registry record missing: {f}")
        return {"method":"GET","endpoint":source.official_source_location,"series_identifier":source.exact_series_identifier,"start_date":start_date.isoformat(),"end_date":end_date.isoformat()}
    def acquire_raw(self, request): raise SourceAcquisitionError("ECB acquisition not yet implemented.")
    def parse_raw(self, raw, source): raise SourceAcquisitionError("No raw data acquired yet.")
    def normalise_observations(self, obs): return obs
    def validate_source_response(self, raw, source): return False
