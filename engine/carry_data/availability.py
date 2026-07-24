"""Availability and lookahead guard for FX carry rate panel."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .models import Observation


def get_available_rates(
    observations: List[Observation],
    decision_timestamp_utc: datetime,
) -> List[Observation]:
    """
    Return only observations whose publication_timestamp_utc is at or before
    the decision timestamp. Uses publication_timestamp_utc, not observation_date.

    This enforces the lookahead safety rule: a rate may only be used after
    its documented publication time.
    """
    if decision_timestamp_utc.tzinfo is None:
        decision_timestamp_utc = decision_timestamp_utc.replace(tzinfo=timezone.utc)

    return [
        obs for obs in observations
        if obs.publication_timestamp_utc <= decision_timestamp_utc
    ]
