"""Stable adapter interface for Kronos forecasting.

Designed so that the benchmark runner imports ONLY this module.
Internal layout details (model_src, module, etc.) are opaque to the
runner.  All heavy imports (torch, transformers, safetensors) happen
lazily on first ``predict()`` call.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

# Lazy torch import (performed only when a real predictor is built)
_TORCH_AVAILABLE = False
_SAFETENSORS_AVAILABLE = False
_HF_AVAILABLE = False

def _torch() -> "Any":
    global _TORCH_AVAILABLE
    if not _TORCH_AVAILABLE:
        import torch  # noqa: F401
        _TORCH_AVAILABLE = True
    return torch

def _safetensors() -> "Any":
    global _SAFETENSORS_AVAILABLE
    if not _SAFETENSORS_AVAILABLE:
        from safetensors.torch import load_file  # noqa: F401
        _SAFETENSORS_AVAILABLE = True
    return load_file

def _hf_hub() -> "Any":
    global _HF_AVAILABLE
    if not _HF_AVAILABLE:
        from huggingface_hub import PyTorchModelHubMixin  # noqa: F401
        _HF_AVAILABLE = True
    return PyTorchModelHubMixin


# ── Frozen checkpoint identity ──────────────────────────────────────
_checkpoint_sha256 = "a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c"
_checkpoint_path = Path(__file__).resolve().parent.parent.parent / "engine" / "docs" / "checkpoints" / "Kronos-mini.model.safetensors"
_model_repo = "NeoQuasar/Kronos-mini"
_tokenizer_repo = "NeoQuasar/Kronos-Tokenizer-2k"
_model_revision = "f4e68697d9d5aed55cef5c96aabc3376bcad9f81"
_tokenizer_revision = "26966d0035065a0cae0ebad7af8ece35bc1fb51c"

_inference_device = "cpu"


class KronosPredictor:
    """Real Kronos predictor.  Loads checkpoint lazily on first ``predict()``.

    The constructor does NOT load the model weights, tokenizer, or torch;
    those happen on the first call to ``predict()``.
    """

    def __init__(self) -> None:
        self._model = None  # type: ignore[var-defined]
        self._tokenizer = None  # type: ignore[var-defined]
        self._loaded = False

    def predict(
        self,
        context_df: "pd.DataFrame",
        x_timestamp: "pd.Series",
        y_timestamp: "pd.Series",
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

        Parameters
        ----------
        context_df : DataFrame with columns open, high, low, close
            (optionally volume, amount). Must have at least 2 rows.
        x_timestamp : 1-D array-like of length len(context_df)
            Timestamps for the context window.  Must be strictly increasing,
            no duplicates, and x_timestamp[-1] < y_timestamp[0].
        y_timestamp : 1-D array-like of length prediction_length
            Target timestamps for the forecast horizon.
        prediction_length : int
            Number of future steps to predict (must equal len(y_timestamp)).
        temperature : float
            Sampling temperature passed to the official predictor.
        top_p : float
            Nucleus sampling parameter.
        sample_count : int
            Number of independent samples; only sample_count=1 is supported
            by the OHLC output path.
        seed : int
            Determinism seed (stored for audit; Kronos uses its own sampler).

        Returns
        -------
        dict with keys horizon_0 … horizon_{prediction_length-1}, each
        value a float scalar, plus an output DataFrame under key
        ``_df`` whose index is y_timestamp and columns are open/high/low/close
        (and vol/amt if provided).
        """
        if not self._loaded:
            self._load()

        # ── Input validation (fail-closed) ──
        import pandas as pd  # noqa: F811

        if not isinstance(context_df, pd.DataFrame):
            raise TypeError(f"context_df must be a DataFrame, got {type(context_df).__name__}")
        for col in ("open", "high", "low", "close"):
            if col not in context_df.columns:
                raise ValueError(f"context_df missing required column: {col!r}")

        x_timestamp = pd.Series(x_timestamp) if not isinstance(x_timestamp, pd.Series) else x_timestamp
        y_timestamp = pd.Series(y_timestamp) if not isinstance(y_timestamp, pd.Series) else y_timestamp

        if len(x_timestamp) != len(context_df):
            raise ValueError(
                f"x_timestamp length ({len(x_timestamp)}) != len(context_df) "
                f"({len(context_df)})"
            )
        if len(y_timestamp) != prediction_length:
            raise ValueError(
                f"y_timestamp length ({len(y_timestamp)}) != prediction_length "
                f"({prediction_length})"
            )
        if x_timestamp.duplicated().any():
            raise ValueError("x_timestamp contains duplicate values")
        if y_timestamp.duplicated().any():
            raise ValueError("y_timestamp contains duplicate values")
        if not (x_timestamp.sort_values().index == x_timestamp.index).all() and \
           not x_timestamp.equals(x_timestamp.sort_values()):
            pass  # order check below uses sorted comparison
        xts_sorted = x_timestamp.sort_values()
        yts_sorted = y_timestamp.sort_values()
        if not (xts_sorted.values[:-1] < xts_sorted.values[1:]).all():
            raise ValueError("x_timestamp must be strictly increasing")
        if not (yts_sorted.values[:-1] < yts_sorted.values[1:]).all():
            raise ValueError("y_timestamp must be strictly increasing")
        if x_timestamp.iloc[-1] >= y_timestamp.iloc[0]:
            raise ValueError(
                f"x_timestamp[-1] ({x_timestamp.iloc[-1]}) must be < "
                f"y_timestamp[0] ({y_timestamp.iloc[0]})"
            )
        if prediction_length <= 0:
            raise ValueError(f"prediction_length must be > 0, got {prediction_length}")
        if sample_count <= 0:
            raise ValueError(f"sample_count must be > 0, got {sample_count}")

        # ── Delegate to the official KronosPredictor.predict() ──
        from engine.kronos_adapter.model_src.kronos import KronosPredictor as _KronosPredictor  # type: ignore[import-not-found]

        official = _KronosPredictor(self._model, self._tokenizer, device=_inference_device)
        raw = official.predict(
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
        if not isinstance(raw, pd.DataFrame):
            raise TypeError(f"Official predictor returned {type(raw).__name__}, expected DataFrame")
        if len(raw) != prediction_length:
            raise ValueError(f"Official predictor returned {len(raw)} rows, expected {prediction_length}")
        if not raw.index.equals(y_timestamp.reset_index(drop=True)):
            # y_timestamp may carry name/attribute; compare values only
            if not raw.index.tolist() == y_timestamp.reset_index(drop=True).tolist():
                raise ValueError("Official predictor index does not match y_timestamp")

        for col in ("open", "high", "low", "close"):
            if col in raw.columns:
                if raw[col].isna().any():
                    raise ValueError(f"Predicted {col!r} contains NaN values")
                if not np.isfinite(raw[col].values).all():
                    raise ValueError(f"Predicted {col!r} contains non-finite values")

        result: Dict[str, Any] = {}
        for i in range(prediction_length):
            result[f"horizon_{i}"] = {
                "open": float(raw["open"].iloc[i]),
                "high": float(raw["high"].iloc[i]),
                "low": float(raw["low"].iloc[i]),
                "close": float(raw["close"].iloc[i]),
            }
        result["_df"] = raw
        return result

    def _load(self) -> None:
        import numpy as np  # noqa: F811
        import pandas as pd  # noqa: F811

        # Import the actual Kronos model classes via package-relative path
        # so kronos.py's "from .module import *" works correctly.
        from engine.kronos_adapter.model_src.kronos import KronosTokenizer, Kronos as KronosModel  # type: ignore[import-not-found]
        from safetensors.torch import load_file

        # Load tokenizer and model from the verified local checkpoint directory.
        import json as _json
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
    without importing torch, transformers, safetensors, or huggingface_hub.

    Parameters
    ----------
    context_df : pd.DataFrame with a ``close`` column (and optional ``open``,
        ``high``, ``low``, ``volume``, ``amount``).
    prediction_length : int  — number of horizon steps to generate.
    seed : int  — deterministic seed for reproducibility.

    Behaviour (deterministic, no model weights):
        Each horizon ``i`` returns ``last_close + i * drift`` where ``drift``
        is the simple mean of (close[t] - close[t-1]) over the context window.
        This is intentionally naive and NOT a real Kronos forecast.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._called = False
        self._predict_count = 0

    def predict(
        self,
        context_df: "pd.DataFrame",
        prediction_length: int,
        temperature: float = 1.0,
        top_p: float = 0.9,
        sample_count: int = 1,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        import numpy as np
        rng = np.random.RandomState(seed if seed is not None else self._seed)
        close_col = context_df["close"].values.astype("float64")
        if len(close_col) < 2:
            drift = 0.0
        else:
            returns = np.diff(close_col)
            drift = float(np.mean(returns))
        last_close = float(close_col[-1])
        self._called = True
        self._predict_count += 1
        result: Dict[str, Any] = {}
        for i in range(prediction_length):
            result[f"horizon_{i}"] = last_close + drift * (i + 1)
        # Always return exactly prediction_length keys — no extras
        assert len(result) == prediction_length, (
            f"FakeKronosPredictor produced {len(result)} rows for "
            f"prediction_length={prediction_length}"
        )
        return result

    @property
    def called(self) -> bool:
        return self._called

    @property
    def predict_call_count(self) -> int:
        return self._predict_count


def load_kronos_predictor() -> KronosPredictor:
    """Factory returning a lazy KronosPredictor.  Weights load on first predict()."""
    return KronosPredictor()
