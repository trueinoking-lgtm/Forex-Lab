"""Structured result object for raw/projected OHLC predictions.

This is the canonical production interface between the predictor and
all consumers (runner, replay, tamper detection, metric computation).

Every active consumer and test must use this type — no reliance on
magic keys such as ``_raw`` or ``_projected`` as the authoritative
contract.
"""
from __future__ import annotations

import dataclasses as _dc
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


@_dc.dataclass(frozen=True, slots=True)
class KronosPredictionResult:
    """Immutable, fully specified prediction result for one forecast horizon.

    Attributes
    ----------
    raw_predictions : pd.DataFrame
        Byte-for-byte raw model output.  Columns: open, high, low, close
        (and optionally volume, amount).  Never modified by the adapter.
    projected_predictions : pd.DataFrame
        Deterministic structural projection.  OHLC values are valid even
        when the raw model produces structurally impossible candles.
    projection_metadata : Dict[str, Any]
        Meta-information about the projection, keys:
        - ``projection_applied`` (bool)
        - ``high_adjustments`` (List[float]) per-row absolute high adjustment
        - ``low_adjustments`` (List[float]) per-row absolute low adjustment
        - ``total_absolute_adjustment`` (float)
        - ``relative_adjustment_to_origin_close`` (float or None for zero close)
    raw_validity : pd.Series[bool]
        Per-row validity flag for the raw predictions.
    projected_validity : pd.Series[bool]
        Per-row validity flag for the projected predictions.
    predictor_identity : Dict[str, Any]
        Identifies the predictor and checkpoint used.
    evidence_metadata : Dict[str, Any]
        Metadata for evidence serialization and replay.
    """

    raw_predictions: pd.DataFrame
    projected_predictions: pd.DataFrame
    projection_metadata: Dict[str, Any]
    raw_validity: pd.Series
    projected_validity: pd.Series
    predictor_identity: Dict[str, Any]
    evidence_metadata: Dict[str, Any]

    # ── Convenience accessors ──────────────────────────────────

    @property
    def projection_applied(self) -> bool:
        return bool(self.projection_metadata.get("projection_applied"))

    @property
    def high_adjustments(self) -> List[float]:
        return list(self.projection_metadata.get("high_adjustments", []))

    @property
    def low_adjustments(self) -> List[float]:
        return list(self.projection_metadata.get("low_adjustments", []))

    @property
    def total_absolute_adjustment(self) -> float:
        return float(self.projection_metadata.get("total_absolute_adjustment", 0.0))

    @property
    def relative_adjustment_to_origin_close(
        self,
    ) -> Optional[float]:
        val = self.projection_metadata.get("relative_adjustment_to_origin_close")
        return None if val is None else float(val)

    # ── Serialization ──────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict for evidence writing."""
        return {
            "raw_predictions": _df_to_serializable(self.raw_predictions),
            "projected_predictions": _df_to_serializable(self.projected_predictions),
            "projection_metadata": self.projection_metadata,
            "raw_validity": [bool(v) for v in self.raw_validity],
            "projected_validity": [bool(v) for v in self.projected_validity],
            "predictor_identity": self.predictor_identity,
            "evidence_metadata": self.evidence_metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KronosPredictionResult:
        """Deserialize from the output of ``to_dict()``."""
        return cls(
            raw_predictions=_df_from_serializable(data["raw_predictions"]),
            projected_predictions=_df_from_serializable(
                data["projected_predictions"]
            ),
            projection_metadata=data["projection_metadata"],
            raw_validity=pd.Series(data["raw_validity"]),
            projected_validity=pd.Series(data["projected_validity"]),
            predictor_identity=data["predictor_identity"],
            evidence_metadata=data["evidence_metadata"],
        )


def _df_to_serializable(df: pd.DataFrame) -> Dict[str, Any]:
    """Convert a DataFrame to a JSON-serialisable dict (records-oriented)."""
    return {
        "columns": list(df.columns),
        "index": [str(i) for i in df.index],
        "data": df.to_dict(orient="list"),
    }


def _df_from_serializable(payload: Dict[str, Any]) -> pd.DataFrame:
    """Reconstruct a DataFrame from the serialisable dict format."""
    return pd.DataFrame(
        payload["data"],
        index=pd.Index(payload["index"], name=payload.get("index_name")),
        columns=payload["columns"],
    )


# ── Backward-compatibility shims ──────────────────────────────────────


def _legacy_dict_to_result(
    legacy: Dict[str, Any],
    predictor_identity: Dict[str, Any],
    evidence_metadata: Dict[str, Any],
) -> KronosPredictionResult:
    """Convert an old-style prediction dict (with ``_raw``/``_projected`` keys)
    to the new explicit contract."""

    raw_df = legacy["_raw"] if "_raw" in legacy else pd.DataFrame()
    proj_df = legacy["_projected"] if "_projected" in legacy else pd.DataFrame()

    return KronosPredictionResult(
        raw_predictions=raw_df,
        projected_predictions=proj_df,
        projection_metadata={
            "projection_applied": legacy.get("_projection_applied", False),
            "high_adjustments": legacy.get("_projection_high_adjustments", []),
            "low_adjustments": legacy.get("_projection_low_adjustments", []),
            "total_absolute_adjustment": legacy.get(
                "_total_absolute_adjustment", 0.0
            ),
            "relative_adjustment_to_origin_close": legacy.get(
                "_relative_adjustment_to_origin_close"
            ),
        },
        raw_validity=pd.Series([True] * len(raw_df)),
        projected_validity=pd.Series([True] * len(proj_df)),
        predictor_identity=predictor_identity,
        evidence_metadata=evidence_metadata,
    )