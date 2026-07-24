"""Base adapter class and error type for FX carry source adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import List

from ..models import Observation, SourceRecord


class SourceAcquisitionError(Exception):
    """Raised when a source acquisition fails or the registry record is incomplete."""


class BaseSourceAdapter(ABC):
    """Common interface for all FX carry benchmark source adapters."""

    @abstractmethod
    def identify_source(self) -> str:
        """Return the adapter's source identifier string."""

    @abstractmethod
    def build_request(self, source: SourceRecord, start_date: date, end_date: date) -> dict:
        """Build a request dict from the source record and date range."""

    @abstractmethod
    def acquire_raw(self, request: dict) -> bytes:
        """Execute the request and return raw response bytes."""

    @abstractmethod
    def parse_raw(self, raw: bytes, source: SourceRecord) -> List[Observation]:
        """Parse raw response bytes into Observation objects."""

    @abstractmethod
    def normalise_observations(self, observations: List[Observation]) -> List[Observation]:
        """Validate and normalise observations (dedup, date checks, quality flags)."""

    @abstractmethod
    def validate_source_response(self, raw: bytes, source: SourceRecord) -> bool:
        """Validate that the raw response matches expectations for this source."""
