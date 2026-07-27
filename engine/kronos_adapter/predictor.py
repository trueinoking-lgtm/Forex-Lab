"""Stable adapter interface for Kronos forecasting with raw/projected OHLC separation.

Designed so that the benchmark runner imports ONLY this module.
All heavy imports (torch, transformers, safetensors) happen lazily
on first ``predict()`` call.

Every prediction returns a KronosPredictionResult — a frozen,
explicit dataclass that is the canonical production contract between
predictor, runner, replay, metrics, and tamper detection.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from engine.kronos_adapter.prediction_result import KronosPredictionResult

# Lazy torch import (performed only when a real predictor is built)
_TORCH_AVAILABLE = False
_SAFETENSORS_AVAILABLE = False
_HF_AVAILABLE = False


def _torch() -> Any:
    global _TORCH_AVAILABLE
    if not _TORCH_AVAILABLE:
        import torch  # noqa: F401
        _TORCH_AVAILABLE = True
    return torch


def _safetensors() -> Any:
    global _SAFETENSORS_AVAILABLE
    if not _SAFETENSORS_AVAILABLE:
        from safetensors.torch import load_file  # noqa: F401
        _SAFETENSORS_AVAILABLE = True
    return load_file


def _hf_hub() -> Any:
    global _HF_AVAILABLE
    if not _HF_AVAILABLE:
        from huggingface_hub import PyTorchModelHubMixin  # noqa: F401
        _HF_AVAILABLE = True
    return PyTorchModelHubMixin


# ── Frozen checkpoint identity ──────────────────────────────────────
_checkpoint_sha256 = "a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c"
_checkpoint_path = (
    Path(__file__).resolve().parent.parent.parent
    / "engine"
    / "docs"
    / "checkpoints"
    / "Kronos-mini.model.safetensors"
)
_model_repo = "NeoQuasar/Kronos-mini"
_tokenizer_repo = "NeoQuasar/Kronos-Tokenizer-2k"
_model_revision = "f4e68697d9d5aed55cef5c96aabc3376bcad9f81"
_tokenizer_revision = "26966d0035065a0cae0ebad7af8ece35bc1fb51c"

_inference_device = "cpu"


# ── Deterministic projection ────────────────────────────────────────
def project_ohlc(
    raw_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Produce a structurally valid OHLC projection from raw model output.

    The projection is deterministic and never modifies raw values.

    Projection rules (applied per-row):
      projected_open  = raw_open
      projected_close = raw_close
      projected_high  = max(raw_high, raw_open, raw_close)
      projected_low   = min(raw_low, raw_open, raw_close)
      volume / amount are passed through unchanged.

    Returns dict with keys: projected_df, projection_applied,
    high_adjustments, low_adjustments, total_absolute_adjustment,
    relative_adjustment_to_origin_close, ohlc_valid_flag.
    """
    raw = raw_df.copy()
    adjustments_high = (raw["high"] < raw[["open", "close"]].max(axis=1)).astype(float)
    adjustments_low = (raw["low"] > raw[["open", "close"]].min(axis=1)).astype(float)

    projected = raw.copy()
    projected["high"] = raw[["high", "open", "close"]].max(axis=1)
    projected["low"] = raw[["low", "open", "close"]].min(axis=1)

    high_adj = projected["high"] - raw["high"]
    low_adj = raw["low"] - projected["low"]
    total_abs_adj = (high_adj.abs() + low_adj.abs()).sum()

    origin_close = raw["close"].iloc[-1] if len(raw) > 0 else np.nan
    rel_adj = total_abs_adj / abs(origin_close) if origin_close != 0 and not np.isnan(origin_close) else np.nan

    projection_applied = bool((high_adj > 0).any() or (low_adj > 0).any())
    projected_valid = bool(
        (projected["high"] >= projected[["open", "close"]].max(axis=1)).all()
        and (projected["low"] <= projected[["open", "close"]].min(axis=1)).all()
        and (projected["high"] >= projected["low"]).all()
    )

    return {
        "projected_df": projected,
        "projection_applied": projection_applied,
        "high_adjustments": high_adj,
        "low_adjustments": low_adj,
        "total_absolute_adjustment": float(total_abs_adj),
        "relative_adjustment_to_origin_close": float(rel_adj) if not np.isnan(rel_adj) else None,
        "projected_ohlc_valid": projected_valid,
    }


def _validate_ohlc(df: pd.DataFrame, label: str = "output") -> None:
    """Fail-closed if any row violates OHLC structural invariants."""
    bad_high = df["high"] < df[["open", "close"]].max(axis=1)
    bad_low = df["low"] > df[["open", "close"]].min(axis=1)
    bad_hl = df["high"] < df["low"]
    bad_rows = bad_high | bad_low | bad_hl
    if bad_rows.any():
        idxs = df.index[bad_rows].tolist()
        details = []
        for idx in idxs[:5]:
            row = df.loc[idx]
            details.append(
                f"  idx={idx}: high={row['high']:.6f} max(o,c)={max(row['open'], row['close']):.6f}  "
                f"low={row['low']:.6f} min(o,c)={min(row['open'], row['close']):.6f}"
            )
        raise ValueError(
            f"{label} has {bad_rows.sum()} structurally invalid OHLC rows:\n"
            + "\n".join(details)
        )


class KronosPredictor:
    """Real Kronos predictor.  Loads checkpoint lazily on first ``predict()``.

    The constructor does NOT load the model weights, tokenizer, or torch;
    those happen on the first call to ``predict()``.

    Public interface
    ----------------
    predict(
        context_df,          # DataFrame with columns open, high, low, close
                              # (optionally volume, amount).  Must have >= 2 rows.
        x_timestamp,         # 1-D pd.Series of length len(context_df), strictly increasing
        y_timestamp,         # 1-D pd.Series of length prediction_length, strictly increasing
        prediction_length,   # Number of future steps (must equal len(y_timestamp))
        temperature=1.0,     # Sampling temperature
        top_p=0.9,           # Nucleus sampling
        sample_count=1,      # Independent samples (only 1 supported by OHLC path)
        seed=0,              # Determinism seed (stored for audit)
    ) -> dict

    The returned dict has keys ``horizon_0`` … ``horizon_{prediction_length-1}``
    plus ``_df`` (raw prediction DataFrame), ``_raw``, and ``_projected`` entries.
    """

    def __init__(self) -> None:
        self._model = None  # type: ignore[var-defined]
        self._tokenizer = None  # type: ignore[var-defined]
        self._loaded = False

    def predict(
        self,
        context_df: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        prediction_length: int,
        temperature: float = 1.0,
        top_p: float = 0.9,
        sample_count: int = 1,
        seed: int = 0,
    ) -> Dict[str, Any]:
        """Return a dict of per-horizon forecasts from the real Kronos model.

        Delegates to the official vendored KronosPredictor.predict(), which
        handles preprocessing (normalization, volume/amount defaults,
        timestamp feature construction, batch dimensions) internally.

        The raw model output is NEVER modified. A deterministic projection
        is computed separately for structural quality measurement.
        """
        if not self._loaded:
            self._load()

        # ── Input validation (fail-closed) ──
        if not isinstance(context_df, pd.DataFrame):
            raise TypeError(f"context_df must be a DataFrame, got {type(context_df).__name__}")
        for col in ("open", "high", "low", "close"):
            if col not in context_df.columns:
                raise ValueError(f"context_df missing required column: {col!r}")

        x_timestamp = pd.Series(x_timestamp) if not isinstance(x_timestamp, pd.Series) else x_timestamp
        y_timestamp = pd.Series(y_timestamp) if not isinstance(y_timestamp, pd.Series) else y_timestamp

        if len(x_timestamp) != len(context_df):
            raise ValueError(
                f"x_timestamp length ({len(x_timestamp)}) != len(context_df) ({len(context_df)})"
            )
        if len(y_timestamp) != prediction_length:
            raise ValueError(
                f"y_timestamp length ({len(y_timestamp)}) != prediction_length ({prediction_length})"
            )
        if prediction_length <= 0:
            raise ValueError(f"prediction_length must be > 0, got {prediction_length}")
        if sample_count <= 0:
            raise ValueError(f"sample_count must be > 0, got {sample_count}")
        if x_timestamp.duplicated().any():
            raise ValueError("x_timestamp contains duplicate values")
        if y_timestamp.duplicated().any():
            raise ValueError("y_timestamp contains duplicate values")
        xts_sorted = x_timestamp.sort_values()
        yts_sorted = y_timestamp.sort_values()
        if not (xts_sorted.values[:-1] < xts_sorted.values[1:]).all():
            raise ValueError("x_timestamp must be strictly increasing")
        if not (yts_sorted.values[:-1] < yts_sorted.values[1:]).all():
            raise ValueError("y_timestamp must be strictly increasing")
        if x_timestamp.iloc[-1] >= y_timestamp.iloc[0]:
            raise ValueError(
                f"x_timestamp[-1] must be < y_timestamp[0] (got {x_timestamp.iloc[-1]} >= {y_timestamp.iloc[0]})"
            )

        # ── Delegate to the official KronosPredictor.predict() ──
        from engine.kronos_adapter.model_src.kronos import KronosPredictor as _KronosPredictor  # type: ignore[import-not-found]

        official = _KronosPredictor(self._model, self._tokenizer, device=_inference_device)
        raw_df = official.predict(
            df=context_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=prediction_length,
            T=temperature,
            top_p=top_p,
            sample_count=sample_count,
            verbose=False,
        )

        # ── Output validation (fail-closed) ──
        if not isinstance(raw_df, pd.DataFrame):
            raise TypeError(f"Official predictor returned {type(raw_df).__name__}, expected DataFrame")
        if len(raw_df) != prediction_length:
            raise ValueError(f"Official predictor returned {len(raw_df)} rows, expected {prediction_length}")
        if not raw_df.index.equals(pd.DatetimeIndex(y_timestamp)):
            if not raw_df.index.tolist() == pd.DatetimeIndex(y_timestamp).tolist():
                raise ValueError("Official predictor index does not match y_timestamp")

        required_cols = {"open", "high", "low", "close"}
        present = set(raw_df.columns) & required_cols
        if required_cols - present:
            raise ValueError(f"Official predictor missing columns: {required_cols - present}")

        for col in required_cols:
            if raw_df[col].isna().any():
                raise ValueError(f"Predicted {col!r} contains NaN values")
            if not np.isfinite(raw_df[col].values).all():
                raise ValueError(f"Predicted {col!r} contains non-finite values")

        # ── Compute projection & raw validity ──
        proj = project_ohlc(raw_df)

        # Try structural validation of raw output; if raw invalid, preserve it
        # but flag it — do NOT silently repair
        raw_valid = False
        try:
            _validate_ohlc(raw_df, label="raw model output")
            raw_valid = True
        except ValueError:
            raw_valid = False

        # ── Build canonical KronosPredictionResult ──
        identity = {
            "predictor_class": type(self).__name__,
            "model_identifier": _model_repo,
            "checkpoint_identifier": _model_revision,
            "is_synthetic": False,
            "evidence_eligible": True,
        }
        meta = {
            "forecast_length": prediction_length,
            "context_steps": len(context_df),
            "seed": seed,
            "temperature": temperature,
            "top_p": top_p,
            "sample_count": sample_count,
            "context_hash": hashlib.sha256(context_df.to_json().encode()).hexdigest()[:16],
        }
        return KronosPredictionResult(
            raw_predictions=raw_df,
            projected_predictions=proj["projected_df"],
            projection_metadata={
                "projection_applied": proj["projection_applied"],
                "high_adjustments": proj["high_adjustments"],
                "low_adjustments": proj["low_adjustments"],
                "total_absolute_adjustment": proj["total_absolute_adjustment"],
                "relative_adjustment_to_origin_close": proj["relative_adjustment_to_origin_close"],
            },
            raw_validity=pd.Series([raw_valid] * len(raw_df)),
            projected_validity=pd.Series([proj["projected_ohlc_valid"]] * len(proj["projected_df"])),
            predictor_identity=identity,
            evidence_metadata=meta,
        )

    def _load(self) -> None:
        import json as _json  # noqa: F811

        from engine.kronos_adapter.model_src.kronos import KronosTokenizer, Kronos as KronosModel  # type: ignore[import-not-found]
        from safetensors.torch import load_file

        tokenizer_dir = Path(_checkpoint_path).parent / "tokenizer"
        tokenizer_cfg_path = tokenizer_dir / "config.json"
        tokenizer_config = _json.loads(tokenizer_cfg_path.read_text())
        self._tokenizer = KronosTokenizer(
            d_in=tokenizer_config["d_in"],
            d_model=tokenizer_config["d_model"],
            n_heads=tokenizer_config["n_heads"],
            ff_dim=tokenizer_config["ff_dim"],
            n_enc_layers=tokenizer_config["n_enc_layers"],
            n_dec_layers=tokenizer_config["n_dec_layers"],
            ffn_dropout_p=tokenizer_config["ffn_dropout_p"],
            attn_dropout_p=tokenizer_config["attn_dropout_p"],
            resid_dropout_p=tokenizer_config["resid_dropout_p"],
            s1_bits=tokenizer_config["s1_bits"],
            s2_bits=tokenizer_config["s2_bits"],
            beta=tokenizer_config["beta"],
            gamma0=tokenizer_config["gamma0"],
            gamma=tokenizer_config["gamma"],
            zeta=tokenizer_config["zeta"],
            group_size=tokenizer_config["group_size"],
        )
        tokenizer_sd = load_file(str(tokenizer_dir / "model.safetensors"))
        tk_result = self._tokenizer.load_state_dict(tokenizer_sd, strict=True)
        assert not tk_result.missing_keys, f"tokenizer missing keys: {tk_result.missing_keys}"
        assert not tk_result.unexpected_keys, f"tokenizer unexpected keys: {tk_result.unexpected_keys}"

        model_cfg = _json.loads(Path(_checkpoint_path).parent.joinpath("config.json").read_text())
        self._model = KronosModel(
            s1_bits=model_cfg["s1_bits"],
            s2_bits=model_cfg["s2_bits"],
            n_layers=model_cfg["n_layers"],
            d_model=model_cfg["d_model"],
            n_heads=model_cfg["n_heads"],
            ff_dim=model_cfg["ff_dim"],
            ffn_dropout_p=model_cfg["ffn_dropout_p"],
            attn_dropout_p=model_cfg["attn_dropout_p"],
            resid_dropout_p=model_cfg["resid_dropout_p"],
            token_dropout_p=model_cfg["token_dropout_p"],
            learn_te=model_cfg["learn_te"],
        )
        model_sd = load_file(str(_checkpoint_path))
        model_result = self._model.load_state_dict(model_sd, strict=True)
        assert not model_result.missing_keys, f"model missing keys: {model_result.missing_keys}"
        assert not model_result.unexpected_keys, f"model unexpected keys: {model_result.unexpected_keys}"
        self._model.eval()
        self._loaded = True


class FakeKronosPredictor:
    """Deterministic fake Kronos predictor for unit tests.

    Implements the exact same ``predict()`` interface as ``KronosPredictor``
    with x_timestamp/y_timestamp parameters. Returns raw and projected
    output in the same format.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._called = False
        self._predict_count = 0

    def predict(
        self,
        context_df: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        prediction_length: int,
        temperature: float = 1.0,
        top_p: float = 0.9,
        sample_count: int = 1,
        seed: Optional[int] = None,
    ) -> KronosPredictionResult:
        import numpy as np

        rng = np.random.RandomState(seed if seed is not None else self._seed)
        close_col = context_df["close"].values.astype("float64")
        if len(close_col) < 2:
            drift = 0.0
        else:
            returns = np.diff(close_col)
            drift = float(np.mean(returns))
        last_close = float(close_col[-1])
        last_open = float(close_col[-1])
        last_high = float(close_col[-1])
        last_low = float(close_col[-1])

        self._called = True
        self._predict_count += 1

        raw_rows = []
        for i in range(prediction_length):
            c = last_close + drift * (i + 1)
            h = c + abs(rng.randn()) * 0.01
            l = c - abs(rng.randn()) * 0.01
            o = c + rng.randn() * 0.005
            raw_rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 0.0, "amount": 0.0})

        raw_df = pd.DataFrame(raw_rows, index=pd.DatetimeIndex(y_timestamp))
        proj = project_ohlc(raw_df)
        valid = True

        identity = {
            "predictor_class": type(self).__name__,
            "model_identifier": "fake-kronos-deterministic",
            "checkpoint_identifier": "none",
            "is_synthetic": True,
            "evidence_eligible": False,
        }
        meta = {
            "forecast_length": prediction_length,
            "context_steps": len(context_df),
            "seed": seed,
        }
        return KronosPredictionResult(
            raw_predictions=raw_df,
            projected_predictions=proj["projected_df"],
            projection_metadata={
                "projection_applied": proj["projection_applied"],
                "high_adjustments": proj["high_adjustments"],
                "low_adjustments": proj["low_adjustments"],
                "total_absolute_adjustment": proj["total_absolute_adjustment"],
                "relative_adjustment_to_origin_close": proj["relative_adjustment_to_origin_close"],
            },
            raw_validity=pd.Series([valid] * len(raw_df)),
            projected_validity=pd.Series([True] * len(proj["projected_df"])),
            predictor_identity=identity,
            evidence_metadata=meta,
        )

    @property
    def called(self) -> bool:
        return self._called

    @property
    def predict_call_count(self) -> int:
        return self._predict_count


def load_kronos_predictor() -> KronosPredictor:
    """Factory returning a lazy KronosPredictor.  Weights load on first predict()."""
    return KronosPredictor()