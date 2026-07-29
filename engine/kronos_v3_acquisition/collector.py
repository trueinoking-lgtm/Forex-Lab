"""Frozen-policy validation and immutable storage for prospective D1 bars.

This module deliberately has no dependency on model, benchmark, metric, order,
torch, transformers, or Kronos packages.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

FREEZE_COMMIT = "4815c1b16eb18746d1ddfc717dcaa0e7f3fdf370"
FREEZE_TIME = datetime(2026, 7, 28, 17, 13, 20, tzinfo=timezone.utc)
STUDY_ID = "kronos-phase1-v3-prospective-replication"
APPROVED_PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")


class AcquisitionError(ValueError):
    """Fail-closed acquisition policy violation."""


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise AcquisitionError("timestamp must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_manifest(payload: Mapping[str, object]) -> bytes:
    clean = {key: value for key, value in payload.items()
             if key != "current_manifest_sha256"}
    return json.dumps(
        clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class SourceIdentity:
    broker_company: str
    broker_server: str
    symbol: str
    provider_symbol: str
    timeframe: str
    broker_mode: str


@dataclass(frozen=True)
class D1Bar:
    timestamp: datetime
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None

    @classmethod
    def metadata(cls, timestamp: str | datetime) -> "D1Bar":
        return cls(timestamp=_utc(timestamp))


@dataclass(frozen=True)
class FrozenAcquisitionPolicy:
    active: bool = False
    broker_company: str = "MetaQuotes Ltd."
    broker_server: str = "MetaQuotes-Demo"
    timeframe: str = "D1"
    acquisition_delay: timedelta = timedelta(hours=24)
    pairs: tuple[str, ...] = APPROVED_PAIRS

    def validate_source(self, source: SourceIdentity) -> None:
        expected = {
            "broker_company": self.broker_company,
            "broker_server": self.broker_server,
            "symbol": source.symbol,
            "provider_symbol": source.symbol,
            "timeframe": self.timeframe,
            "broker_mode": "demo",
        }
        actual = source.__dict__
        for field, value in expected.items():
            if actual[field] != value:
                raise AcquisitionError(
                    f"source identity mismatch: {field}={actual[field]!r}, "
                    f"expected {value!r}"
                )
        if source.symbol not in self.pairs:
            raise AcquisitionError(f"unapproved symbol {source.symbol!r}")


def _validate_timestamps(bars: Sequence[D1Bar]) -> None:
    if len(bars) < 2:
        raise AcquisitionError("at least two broker-native D1 timestamps are required")
    timestamps = [bar.timestamp for bar in bars]
    if any(ts.tzinfo is None for ts in timestamps):
        raise AcquisitionError("all timestamps require explicit offsets")
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise AcquisitionError("D1 timestamps must be strictly increasing and unique")


def audit_symbol(
    source: SourceIdentity,
    bars: Sequence[D1Bar],
    acquired_at: str | datetime,
    policy: FrozenAcquisitionPolicy | None = None,
) -> dict[str, object]:
    policy = policy or FrozenAcquisitionPolicy()
    policy.validate_source(source)
    _validate_timestamps(bars)
    acquired = _utc(acquired_at)
    latest = bars[-1].timestamp
    previous = bars[-2].timestamp
    eligible = [
        bar.timestamp
        for index, bar in enumerate(bars[:-1])
        if bar.timestamp > FREEZE_TIME
        and acquired >= bars[index + 1].timestamp + policy.acquisition_delay
    ]
    first_post_freeze = next(
        (bar.timestamp for bar in bars if bar.timestamp > FREEZE_TIME), None
    )
    offsets = sorted({int(bar.timestamp.utcoffset().total_seconds())
                      for bar in bars})
    boundary_minutes = sorted({
        bar.timestamp.astimezone(timezone.utc).hour * 60
        + bar.timestamp.astimezone(timezone.utc).minute
        for bar in bars
    })
    server_offsets = sorted({
        ((24 * 60 - minute) % (24 * 60)) for minute in boundary_minutes
    })
    return {
        "symbol": source.symbol,
        "latest_available_d1_bar_timestamp": _iso(latest),
        "previous_d1_bar_timestamp": _iso(previous),
        "timestamp_utc_offsets_seconds": offsets,
        "broker_server_offsets_inferred_minutes": server_offsets,
        "offsets_vary_across_retrieved_history": (
            len(offsets) > 1 or len(server_offsets) > 1
        ),
        "latest_bar_is_still_forming": True,
        "first_complete_bar_timestamp": _iso(bars[0].timestamp),
        "first_bar_strictly_after_protocol_freeze": (
            _iso(first_post_freeze) if first_post_freeze else None
        ),
        "first_bar_eligible_after_acquisition_delay": (
            _iso(eligible[0]) if eligible else None
        ),
        "proposed_first_eligible_target": _iso(eligible[0]) if eligible else None,
        "metadata_only": all(
            bar.open is None and bar.high is None and bar.low is None and bar.close is None
            for bar in bars
        ),
    }


def audit_common_calendar(audits: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    if set(audits) != set(APPROVED_PAIRS):
        raise AcquisitionError("all four approved pairs are required")
    latest = {item["latest_available_d1_bar_timestamp"] for item in audits.values()}
    previous = {item["previous_d1_bar_timestamp"] for item in audits.values()}
    targets = {item["proposed_first_eligible_target"] for item in audits.values()}
    boundaries = {
        tuple(item["broker_server_offsets_inferred_minutes"])
        for item in audits.values()
    }
    return {
        "all_four_pairs_same_d1_boundary": len(boundaries) == 1,
        "latest_common_calendar": len(latest) == 1 and len(previous) == 1,
        "proposed_first_eligible_target": (
            next(iter(targets)) if len(targets) == 1 else None
        ),
        "mixed_pair_calendars": len(latest) != 1 or len(previous) != 1,
    }


def _decimal_text(value: Decimal | None) -> str:
    if value is None or not value.is_finite():
        raise AcquisitionError("OHLC values must be finite decimals")
    return str(value)


def validate_ohlc_bar(bar: D1Bar) -> None:
    values = (bar.open, bar.high, bar.low, bar.close)
    if any(value is None or not value.is_finite() for value in values):
        raise AcquisitionError("OHLC values must be present and finite")
    assert all(value is not None for value in values)
    if bar.high < max(bar.open, bar.close):
        raise AcquisitionError("high is below open or close")
    if bar.low > min(bar.open, bar.close):
        raise AcquisitionError("low is above open or close")


class ImmutableBatchStore:
    """Append one immutable raw CSV and hash-chained manifest."""

    def __init__(self, root: Path, policy: FrozenAcquisitionPolicy):
        self.root = Path(root)
        self.policy = policy

    def write(
        self,
        source: SourceIdentity,
        bars: Sequence[D1Bar],
        acquired_at: str | datetime,
        receipt_sha256: str,
        collector_commit: str,
        previous_manifest: Path | None = None,
    ) -> tuple[Path, Path]:
        if not self.policy.active:
            raise AcquisitionError("data acquisition is inactive")
        self.policy.validate_source(source)
        _validate_timestamps(bars)
        for bar in bars:
            validate_ohlc_bar(bar)
        acquired = _utc(acquired_at)
        stamp = acquired.strftime("%Y%m%dT%H%M%SZ")
        base = self.root / source.symbol / f"{source.symbol}_{stamp}"
        raw_path = base.with_suffix(".csv")
        manifest_path = base.with_suffix(".manifest.json")
        if raw_path.exists() or manifest_path.exists():
            raise AcquisitionError("duplicate batch or overwrite attempt")

        previous_hash = None
        if previous_manifest is not None:
            previous_bytes = previous_manifest.read_bytes()
            previous_payload = json.loads(previous_bytes)
            calculated = _sha(_canonical_manifest(previous_payload))
            if calculated != previous_payload.get("current_manifest_sha256"):
                raise AcquisitionError("broken previous-manifest hash")
            previous_hash = previous_payload["current_manifest_sha256"]

        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        for bar in bars:
            writer.writerow([
                _iso(bar.timestamp),
                _decimal_text(bar.open),
                _decimal_text(bar.high),
                _decimal_text(bar.low),
                _decimal_text(bar.close),
            ])
        raw = stream.getvalue().encode("utf-8")
        manifest: dict[str, object] = {
            "study_id": STUDY_ID,
            "protocol_commit": FREEZE_COMMIT,
            "external_freeze_receipt_sha256": receipt_sha256,
            "acquisition_timestamp": _iso(acquired),
            "source_company": source.broker_company,
            "source_server": source.broker_server,
            "symbol": source.symbol,
            "timeframe": source.timeframe,
            "first_bar_timestamp": _iso(bars[0].timestamp),
            "last_bar_timestamp": _iso(bars[-1].timestamp),
            "row_count": len(bars),
            "raw_file_sha256": _sha(raw),
            "previous_manifest_sha256": previous_hash,
            "collector_code_commit": collector_commit,
            "acquisition_result": "complete",
        }
        manifest["current_manifest_sha256"] = _sha(_canonical_manifest(manifest))
        encoded_manifest = (
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        self._exclusive_write(raw_path, raw)
        try:
            self._exclusive_write(manifest_path, encoded_manifest)
        except Exception:
            raw_path.unlink(missing_ok=True)
            raise
        return raw_path, manifest_path

    @staticmethod
    def _exclusive_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o444)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
