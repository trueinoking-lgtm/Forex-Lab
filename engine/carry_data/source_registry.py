"""Load and validate the FX carry source registry."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List

from .models import SourceRecord

REQUIRED_FIELDS = [
    "currency", "benchmark_name", "institution", "official_source_location",
    "exact_series_identifier", "benchmark_type", "secured_or_unsecured",
    "frequency", "observation_timezone", "value_date_semantics",
    "publication_time", "publication_lag", "first_available_date",
    "latest_available_date", "revision_policy", "methodology_changes",
    "holiday_handling", "missing_value_policy", "machine_readable_format",
    "access_requirements",
    "licensing_or_redistribution_restrictions",
    "intended_research_role", "known_limitations",
    "methodology_regime",
]


def load_registry(path: str = "engine/config/fx_carry_source_registry.json") -> List[SourceRecord]:
    p = Path(path)
    raw = json.loads(p.read_text())
    records = []
    for item in raw:
        records.append(SourceRecord(**{k: item.get(k) for k in REQUIRED_FIELDS}))
    return records


def get_canonical_sources(registry: List[SourceRecord] = None) -> List[SourceRecord]:
    if registry is None:
        registry = load_registry()
    return [
        r for r in registry
        if r.benchmark_type not in ("policy_rate_weekly", "policy_rate_daily")
        and r.benchmark_type != "policy_rate_cross_check"
        and r.intended_research_role != "diagnostic or forward/term comparison only; not the primary overnight AUD carry input"
    ]


def get_source_by_currency(currency: str, registry: List[SourceRecord] = None) -> List[SourceRecord]:
    if registry is None:
        registry = load_registry()
    return [r for r in registry if r.currency == currency]


def validate_registry(source_registry: List[SourceRecord]) -> None:
    # Fields required for all records
    universal_required = [f for f in REQUIRED_FIELDS if f != "methodology_regime"]
    # Records that must have methodology_regime (canonical daily benchmarks)
    canonical_types = ("overnight_unsecured", "overnight_secured", "overnight_transaction")
    missing = []
    for i, rec in enumerate(source_registry):
        for field in universal_required:
            val = getattr(rec, field, None)
            if val is None or val == "":
                missing.append((i + 1, rec.benchmark_name, field))
        # methodology_regime required only for canonical benchmark types
        if rec.benchmark_type in canonical_types:
            val = getattr(rec, "methodology_regime", None)
            if val is None or val == "":
                missing.append((i + 1, rec.benchmark_name, "methodology_regime"))
    if missing:
        raise ValueError(f"Registry validation failed — missing fields: {missing}")


def registry_hash(path: str = "engine/config/fx_carry_source_registry.json") -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
