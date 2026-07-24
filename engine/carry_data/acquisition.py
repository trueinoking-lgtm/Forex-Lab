"""Acquisition orchestration for FX carry benchmark data."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from .models import AcquisitionManifest, SourceRecord
from .normalization import normalise
from .availability import get_available_rates


class SourceAcquisitionError(Exception):
    """Raised when source acquisition fails."""


class ImmutableAcquisitionError(FileExistsError):
    """Raised when attempting to overwrite an existing acquisition."""


RAW_BASE = Path("engine/data/fx_carry/raw")


def _get_adapter(source: SourceRecord):
    from .adapters.base import BaseSourceAdapter
    institution = (source.institution or "").lower()
    provider = (source.provider or "").lower()

    if "new york fed" in institution:
        from .adapters.new_york_fed import NewYorkFedAdapter
        return NewYorkFedAdapter()
    elif "ecb" in institution or "european central bank" in institution:
        from .adapters.ecb import EcbAdapter
        return EcbAdapter()
    elif "bank of england" in institution:
        from .adapters.bank_of_england import BankOfEnglandAdapter
        return BankOfEnglandAdapter()
    elif "bank of japan" in institution:
        from .adapters.bank_of_japan import BankOfJapanAdapter
        return BankOfJapanAdapter()
    elif "reserve bank of australia" in institution or "rba" in institution:
        from .adapters.rba import RbaAdapter
        return RbaAdapter()
    elif "fred" in provider or "st. louis" in institution:
        from .adapters.fred import FredAdapter
        return FredAdapter()
    else:
        raise SourceAcquisitionError(f"No adapter mapped for institution: {source.institution}")


def acquire_source(source: SourceRecord, start_date, end_date) -> Tuple:
    """Acquire raw data for a source. Returns (manifest, raw_bytes)."""
    adapter = _get_adapter(source)
    request = adapter.build_request(source, start_date, end_date)
    raw = adapter.acquire_raw(request)
    response_sha = hashlib.sha256(raw).hexdigest()
    acquisition_id = uuid.uuid4().hex[:16]
    registry_hash_val = __import__("engine.carry_data.source_registry", fromlist=["registry_hash"]).registry_hash()

    manifest = AcquisitionManifest(
        acquisition_id=acquisition_id,
        source_uri=source.official_source_location,
        response_sha256=response_sha,
        request_metadata={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        acquisition_timestamp_utc=datetime.now(timezone.utc),
        http_status=200,
        content_type="application/octet-stream",
        source_identifier=source.exact_series_identifier,
        requested_date_range=(start_date.isoformat(), end_date.isoformat()),
        parser_version="1.0.0",
        licensing_metadata=source.licensing_or_redistribution_restrictions,
        source_registry_version_hash=registry_hash_val,
        raw_response_path="",
    )
    return manifest, raw


def save_raw(acquisition_id: str, raw_bytes: bytes, manifest: AcquisitionManifest) -> Path:
    """Save raw response to immutable acquisition directory.

    Raises ImmutableAcquisitionError if the acquisition_id already exists
    (immutable storage — never overwrite).
    """
    src_id = manifest.source_identifier.lower().replace(" ", "_")[:60]
    safe_id = acquisition_id.replace("/", "_").replace("\\", "_")
    acq_dir = RAW_BASE / src_id / safe_id
    acq_dir.mkdir(parents=True, exist_ok=True)

    existing_raw = acq_dir / "raw_response.bin"
    if existing_raw.exists():
        raise ImmutableAcquisitionError(
            f"Acquisition {acquisition_id} already has raw_response.bin; "
            "refusing to overwrite (immutable storage)"
        )

    raw_path = acq_dir / "raw_response.bin"
    raw_path.write_bytes(raw_bytes)

    manifest_path = acq_dir / "manifest.json"
    manifest_dict = {
        "acquisition_id": manifest.acquisition_id,
        "source_uri": manifest.source_uri,
        "response_sha256": manifest.response_sha256,
        "request_metadata": manifest.request_metadata,
        "acquisition_timestamp_utc": manifest.acquisition_timestamp_utc.isoformat(),
        "http_status": manifest.http_status,
        "content_type": manifest.content_type,
        "source_identifier": manifest.source_identifier,
        "requested_date_range": list(manifest.requested_date_range),
        "parser_version": manifest.parser_version,
        "licensing_metadata": manifest.licensing_metadata,
        "source_registry_version_hash": manifest.source_registry_version_hash,
    }
    manifest_path.write_text(json.dumps(manifest_dict, indent=2, default=str))

    return raw_path
