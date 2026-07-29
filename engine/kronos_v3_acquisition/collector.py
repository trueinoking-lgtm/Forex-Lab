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
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

FREEZE_COMMIT = "4815c1b16eb18746d1ddfc717dcaa0e7f3fdf370"
FREEZE_TIME = datetime(2026, 7, 28, 17, 13, 20, tzinfo=timezone.utc)
CONSERVATIVE_PROSPECTIVE_START = datetime(
    2026, 7, 29, 9, 0, 0, tzinfo=timezone.utc
)
STUDY_ID = "kronos-phase1-v3-prospective-replication"
APPROVED_PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
CONTAMINATION_CUTOFFS = {
    "EURUSD": datetime(2010, 2, 1, 20, 0, tzinfo=timezone.utc),
    "GBPUSD": datetime(2010, 2, 1, 20, 0, tzinfo=timezone.utc),
    "AUDUSD": datetime(2010, 2, 1, 20, 0, tzinfo=timezone.utc),
    "USDJPY": datetime(2010, 2, 1, 21, 0, tzinfo=timezone.utc),
}


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
    return _utc(value).isoformat(timespec="seconds")


def _iso_original(value: datetime) -> str:
    if value.tzinfo is None:
        raise AcquisitionError("timestamp must include an explicit UTC offset")
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
        parsed = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            raise AcquisitionError("timestamp must include an explicit UTC offset")
        return cls(timestamp=parsed)


@dataclass(frozen=True)
class PairObservation:
    source: SourceIdentity
    target: D1Bar
    next_open: datetime


@dataclass(frozen=True)
class SignedAcquisitionAuthorization:
    study_id: str
    conservative_start: str
    authorised_at: str
    signer: str
    signature: str

    def payload(self) -> bytes:
        return json.dumps(
            {
                "authorised_at": self.authorised_at,
                "conservative_start": self.conservative_start,
                "signer": self.signer,
                "study_id": self.study_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


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
    timestamps = [_utc(bar.timestamp) for bar in bars]
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
    latest = _utc(bars[-1].timestamp)
    previous = _utc(bars[-2].timestamp)
    eligible = [
        _utc(bar.timestamp)
        for index, bar in enumerate(bars[:-1])
        if _utc(bar.timestamp) > CONSERVATIVE_PROSPECTIVE_START
        and _utc(bar.timestamp) > CONTAMINATION_CUTOFFS[source.symbol]
        and acquired >= _utc(bars[index + 1].timestamp) + policy.acquisition_delay
    ]
    first_post_freeze = next(
        (_utc(bar.timestamp) for bar in bars
         if _utc(bar.timestamp) > CONSERVATIVE_PROSPECTIVE_START), None
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
        "latest_available_d1_bar_timestamp_original": _iso_original(
            bars[-1].timestamp
        ),
        "previous_d1_bar_timestamp": _iso(previous),
        "previous_d1_bar_timestamp_original": _iso_original(
            bars[-2].timestamp
        ),
        "timestamp_utc_offsets_seconds": offsets,
        "broker_server_offsets_inferred_minutes": server_offsets,
        "offsets_vary_across_retrieved_history": (
            len(offsets) > 1 or len(server_offsets) > 1
        ),
        "latest_bar_is_still_forming": True,
        "latest_bar_status_basis": (
            "No subsequent broker-native D1 opening timestamp exists in the "
            "retrieved sequence, so the latest opening cannot be completeness proof."
        ),
        "previous_bar_is_complete": True,
        "previous_bar_next_open_completeness_proof": _iso(latest),
        "previous_bar_next_open_completeness_proof_original": _iso_original(
            bars[-1].timestamp
        ),
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
    """Atomically append four raw files and one hash-chained common manifest."""

    def __init__(
        self,
        root: Path,
        policy: FrozenAcquisitionPolicy,
        signature_verifier=None,
    ):
        self.root = Path(root)
        self.policy = policy
        self.signature_verifier = signature_verifier

    def write(
        self,
        source: SourceIdentity,
        bars: Sequence[D1Bar],
        acquired_at: str | datetime,
        receipt_sha256: str,
        collector_commit: str,
        previous_manifest: Path | None = None,
    ) -> tuple[Path, Path]:
        raise AcquisitionError(
            "single-pair write is prohibited; use write_common_batch with all four pairs"
        )

    def write_common_batch(
        self,
        observations: Mapping[str, PairObservation],
        acquired_at: str | datetime,
        receipt_sha256: str,
        collector_commit: str,
        authorization: SignedAcquisitionAuthorization,
        previous_manifest: Path | None = None,
    ) -> tuple[Path, Path]:
        if not self.policy.active:
            raise AcquisitionError("data acquisition is inactive")
        if authorization.study_id != STUDY_ID:
            raise AcquisitionError("signed authorisation has wrong study ID")
        if authorization.conservative_start != _iso(CONSERVATIVE_PROSPECTIVE_START):
            raise AcquisitionError("signed authorisation has wrong prospective start")
        if not callable(self.signature_verifier) or not self.signature_verifier(
            authorization.payload(), authorization.signature, authorization.signer
        ):
            raise AcquisitionError("signed acquisition authorisation is invalid")
        if set(observations) != set(APPROVED_PAIRS):
            raise AcquisitionError("exactly one observation for all four pairs is required")

        acquired = _utc(acquired_at)
        targets = set()
        encoded_raw: dict[str, bytes] = {}
        sources: dict[str, dict[str, str]] = {}
        next_opens: dict[str, str] = {}
        for symbol in APPROVED_PAIRS:
            observation = observations[symbol]
            if observation.source.symbol != symbol:
                raise AcquisitionError("pair key/source substitution detected")
            self.policy.validate_source(observation.source)
            validate_ohlc_bar(observation.target)
            target = _utc(observation.target.timestamp)
            next_open = _utc(observation.next_open)
            if target <= CONSERVATIVE_PROSPECTIVE_START:
                raise AcquisitionError("target is not strictly after conservative start")
            if target <= CONTAMINATION_CUTOFFS[symbol]:
                raise AcquisitionError("target overlaps contamination cutoff")
            if next_open <= target:
                raise AcquisitionError("next-open completeness proof must follow target")
            if acquired < next_open + self.policy.acquisition_delay:
                raise AcquisitionError("24-hour acquisition delay has not elapsed")
            targets.add(target)
            next_opens[symbol] = _iso(next_open)
            encoded_raw[symbol] = self._encode_raw(observation.target)
            sources[symbol] = {
                "broker_company": observation.source.broker_company,
                "broker_server": observation.source.broker_server,
                "provider_symbol": observation.source.provider_symbol,
                "timeframe": observation.source.timeframe,
            }
        if len(targets) != 1:
            raise AcquisitionError("all four pairs must share one target timestamp")
        target = next(iter(targets))
        batch_name = target.strftime("%Y%m%dT%H%M%SZ")
        batch_path = self.root / batch_name
        if batch_path.exists():
            raise AcquisitionError("target previously recorded; overwrite refused")

        previous_hash = None
        if previous_manifest is not None:
            previous_bytes = previous_manifest.read_bytes()
            previous_payload = json.loads(previous_bytes)
            calculated = _sha(_canonical_manifest(previous_payload))
            if calculated != previous_payload.get("current_manifest_sha256"):
                raise AcquisitionError("broken previous-manifest hash")
            previous_hash = previous_payload["current_manifest_sha256"]
        manifest: dict[str, object] = {
            "study_id": STUDY_ID,
            "protocol_commit": FREEZE_COMMIT,
            "external_freeze_receipt_sha256": receipt_sha256,
            "acquisition_timestamp": _iso(acquired),
            "conservative_prospective_start": _iso(CONSERVATIVE_PROSPECTIVE_START),
            "target_timestamp": _iso(target),
            "target_timestamp_original": {
                symbol: _iso_original(observations[symbol].target.timestamp)
                for symbol in APPROVED_PAIRS
            },
            "next_open_completeness_proof": next_opens,
            "sources": sources,
            "raw_files": {
                symbol: {
                    "relative_path": f"{symbol}.csv",
                    "sha256": _sha(encoded_raw[symbol]),
                }
                for symbol in APPROVED_PAIRS
            },
            "previous_manifest_sha256": previous_hash,
            "collector_code_commit": collector_commit,
            "authorisation": {
                "authorised_at": authorization.authorised_at,
                "signer": authorization.signer,
                "signature": authorization.signature,
            },
            "acquisition_result": "complete",
        }
        manifest["current_manifest_sha256"] = _sha(_canonical_manifest(manifest))
        encoded_manifest = (
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{batch_name}.", dir=self.root))
        try:
            for symbol in APPROVED_PAIRS:
                self._exclusive_write(staging / f"{symbol}.csv", encoded_raw[symbol])
            manifest_path = staging / "common_batch.manifest.json"
            self._exclusive_write(manifest_path, encoded_manifest)
            self._verify_staged(staging)
            os.rename(staging, batch_path)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        final_manifest = batch_path / "common_batch.manifest.json"
        self._verify_staged(batch_path)
        return batch_path, final_manifest

    @staticmethod
    def _encode_raw(bar: D1Bar) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        writer.writerow([
            _iso_original(bar.timestamp),
            _decimal_text(bar.open),
            _decimal_text(bar.high),
            _decimal_text(bar.low),
            _decimal_text(bar.close),
        ])
        return stream.getvalue().encode("utf-8")

    @staticmethod
    def _verify_staged(directory: Path) -> None:
        manifest_path = directory / "common_batch.manifest.json"
        payload = json.loads(manifest_path.read_bytes())
        if _sha(_canonical_manifest(payload)) != payload["current_manifest_sha256"]:
            raise AcquisitionError("post-write common-manifest hash verification failed")
        for symbol, identity in payload["raw_files"].items():
            data = (directory / identity["relative_path"]).read_bytes()
            if _sha(data) != identity["sha256"]:
                raise AcquisitionError(f"post-write raw hash mismatch for {symbol}")

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
