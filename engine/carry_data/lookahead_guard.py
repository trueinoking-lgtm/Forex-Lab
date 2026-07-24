"""Lookahead safety guard for FX carry canonical panel."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .models import Observation, SourceRecord


def get_available_rates(
    observations: List[Observation],
    decision_timestamp_utc: datetime,
    source: SourceRecord = None,
) -> List[Observation]:
    """
    Return only observations whose publication_timestamp_utc <= decision_timestamp_utc.

    Uses publication_timestamp_utc, never observation_date alone.
    This enforces the lookahead safety rule from Phase 0:
    a rate observation may only become usable after its documented publication time.
    """
    if decision_timestamp_utc.tzinfo is None:
        decision_timestamp_utc = decision_timestamp_utc.replace(tzinfo=timezone.utc)

    result = [
        obs for obs in observations
        if obs.publication_timestamp_utc <= decision_timestamp_utc
    ]
    return result


def check_lookahead_violations(
    observations: List[Observation],
    decision_timestamp_utc: datetime,
) -> List[Observation]:
    """Return observations that would be lookahead violations (published after decision time)."""
    if decision_timestamp_utc.tzinfo is None:
        decision_timestamp_utc = decision_timestamp_utc.replace(tzinfo=timezone.utc)

    return [
        obs for obs in observations
        if obs.publication_timestamp_utc > decision_timestamp_utc
    ]
