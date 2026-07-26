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
        prediction_length: int,
        temperature: float = 1.0,
        top_p: float = 0.9,
        sample_count: int = 1,
        seed: int = 0,
    ) -> Dict[str, Any]:
        """Return a dict of per-horizon predictions.

        Returns
        -------
        dict with key ``horizon_{i}`` for i in 0..prediction_length-1,
        each value an ndarray of scalars.
        """
        if not self._loaded:
            self._load()
        # Delegate to the actual Kronos model inside model_src
        # Import via package-relative path so kronos.py's
        # "from .module import *" works correctly.
        from engine.kronos_adapter.model_src.kronos import KronosPredictor as _KronosPredictor  # type: ignore[import-not-found]

        predictor = _KronosPredictor(
            self._model, self._tokenizer, device=_inference_device
        )
        x = context_df.to_numpy(dtype="float32")
        x_stamp = context_df.index  # assume DatetimeIndex or integer index
        y_stamp = None  # let Kronos autoregressively generate y_stamp
        raw = predictor.generate(
            x=x,
            x_stamp=list(x_stamp),
            y_stamp=y_stamp,
            pred_len=prediction_length,
            T=temperature,
            top_k=0,
            top_p=top_p,
            sample_count=sample_count,
            verbose=False,
        )
        # raw is a list of arrays (one per sample); we take the first
        pred = raw[0] if isinstance(raw, list) else raw
        result: Dict[str, Any] = {}
        for i in range(prediction_length):
            result[f"horizon_{i}"] = float(pred[int(i)]) if pred.ndim == 1 else float(pred[i])
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
