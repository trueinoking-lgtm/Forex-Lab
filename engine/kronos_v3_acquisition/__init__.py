"""Read-only, inference-free prospective D1 acquisition infrastructure."""

from .collector import (
    AcquisitionError,
    D1Bar,
    FrozenAcquisitionPolicy,
    ImmutableBatchStore,
    SourceIdentity,
    audit_common_calendar,
    audit_symbol,
)

__all__ = [
    "AcquisitionError",
    "D1Bar",
    "FrozenAcquisitionPolicy",
    "ImmutableBatchStore",
    "SourceIdentity",
    "audit_common_calendar",
    "audit_symbol",
]
