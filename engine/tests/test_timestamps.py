from datetime import datetime, timedelta, timezone

import pytest

from src.execution.bridge_validation import tick_age_seconds


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def test_tick_age_rejects_future_missing_and_malformed_timestamps():
    assert tick_age_seconds((NOW + timedelta(minutes=10)).isoformat(), NOW) is None
    assert tick_age_seconds("", NOW) is None
    assert tick_age_seconds("not-a-timestamp", NOW) is None


def test_tick_age_accepts_past_timestamp():
    timestamp = (NOW - timedelta(seconds=10)).isoformat()
    assert tick_age_seconds(timestamp, NOW) == pytest.approx(10.0)
