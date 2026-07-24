"""Normalization and validation for FX carry observations."""
from __future__ import annotations

from datetime import date, datetime
from typing import List

from .models import Observation

PARSER_VERSION = "1.0.0"


def normalise(source: object, raw_bytes: bytes) -> List[Observation]:
    """
    Normalise raw bytes into observations.
    This is a stub — actual parsers are adapter-specific.
    Returns empty list; adapters should override parsing.
    """
    return []


def validate_observations(observations: List[Observation]) -> List[Observation]:
    """Validate observations: no duplicates, no malformed dates, no non-numeric rates."""
    seen = set()
    cleaned = []
    for obs in observations:
        # Check for duplicates
        key = (obs.observation_date, obs.currency, obs.benchmark_name, obs.methodology_regime)
        if key in seen:
            continue
        seen.add(key)

        # Check date validity
        if not isinstance(obs.observation_date, date):
            continue

        # Check rate is numeric
        if not isinstance(obs.benchmark_rate_percent, (int, float)):
            continue

        # Check publication timestamp is timezone-aware
        if obs.publication_timestamp_utc.tzinfo is None:
            obs.publication_timestamp_utc = obs.publication_timestamp_utc.replace(tzinfo=datetime.timezone.utc)

        cleaned.append(obs)

    return cleaned
