"""Run one auditable real-Kronos synthetic boundary smoke case."""
from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np
import pandas as pd

from engine.kronos_adapter import load_kronos_predictor


def synthetic_fixture(with_volume: bool) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    x_timestamp = pd.Series(pd.date_range("2025-01-01", periods=50, freq="D", tz="UTC"))
    y_timestamp = pd.Series(pd.date_range("2025-02-20", periods=5, freq="D", tz="UTC"))
    position = np.arange(50, dtype=float)
    close = 100.0 + 0.07 * position + 0.4 * np.sin(position / 4.0)
    frame = pd.DataFrame(
        {
            "open": close - 0.04 * np.cos(position / 5.0),
            "high": np.maximum(close - 0.04 * np.cos(position / 5.0), close) + 0.2,
            "low": np.minimum(close - 0.04 * np.cos(position / 5.0), close) - 0.2,
            "close": close,
        }
    )
    if with_volume:
        frame["volume"] = 1000.0 + 10.0 * position + 25.0 * np.sin(position / 6.0)
        frame["amount"] = frame["volume"] * frame[["open", "high", "low", "close"]].mean(axis=1)
    return frame, x_timestamp, y_timestamp


def run(with_volume: bool) -> dict:
    frame, x_timestamp, y_timestamp = synthetic_fixture(with_volume)
    started = time.perf_counter()
    result = load_kronos_predictor().predict(
        context_df=frame,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        prediction_length=5,
        seed=0,
        temperature=1.0,
        top_p=0.9,
        sample_count=1,
    )
    elapsed = time.perf_counter() - started
    output = result.raw_predictions
    finite = bool(np.isfinite(output.select_dtypes(include=[np.number]).to_numpy()).all())
    valid = bool(
        (output["high"] >= output[["open", "close"]].max(axis=1)).all()
        and (output["low"] <= output[["open", "close"]].min(axis=1)).all()
    )
    return {
        "execution_mode": "synthetic_test",
        "predictor_type": "kronos",
        "is_synthetic": True,
        "evidence_eligible": False,
        "case": "ohlcv" if with_volume else "ohlc_only",
        "input_dataframe_shape": list(frame.shape),
        "x_timestamp_shape": list(x_timestamp.shape),
        "y_timestamp_shape": list(y_timestamp.shape),
        "output_shape": list(output.shape),
        "output_columns": list(output.columns),
        "output_index": [timestamp.isoformat() for timestamp in output.index],
        "inference_time_seconds": elapsed,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "nan_inf_check": finite,
        "ohlc_validity": valid,
        "exit_code": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("ohlc-only", "ohlcv"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.case == "ohlcv")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
