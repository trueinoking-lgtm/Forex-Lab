"""Kronos adapter for the Aether Forex Lab benchmark.

Public interface (importable from repository root):

    from engine.kronos_adapter import load_kronos_predictor, FakeKronosPredictor

The real predictor loads the frozen Kronos-mini checkpoint lazily on first
call.  The fake predictor implements the same ``predict()`` interface with
deterministic, reproducible forecasts suitable for unit tests — it never
downloads weights or loads torch/tokenizers.
"""

from .predictor import FakeKronosPredictor, KronosPredictor, load_kronos_predictor

__all__ = [
    "KronosPredictor",
    "FakeKronosPredictor",
    "load_kronos_predictor",
]
