"""Kronos Phase 1 V2 benchmark execution.

The real predictor is lazy-loaded. Importing this module does not import torch,
transformers, or the upstream model implementation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from engine.kronos_adapter import FakeKronosPredictor, load_kronos_predictor

BASE = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = BASE / "engine/docs/kronos_phase1_v2_config.json"
DEFAULT_DATASET_MANIFEST = BASE / "engine/docs/kronos_phase1_v2_dataset_manifest.json"
DEFAULT_FOLD_MANIFEST = BASE / "engine/docs/kronos_phase1_v2_fold_manifest.json"
DEFAULT_ORIGIN_MANIFEST = BASE / "engine/docs/manifests/kronos_phase1_v2_origin_manifest.json"
DEFAULT_METRIC_SPEC = BASE / "engine/docs/kronos_phase1_v2_metric_spec.json"
DEFAULT_OUTPUT = BASE / "engine/evidence/kronos/phase1"

STAGES = ("synthetic_test", "development", "validation", "sealed_test")
REAL_STAGES = ("development", "validation", "sealed_test")
BASELINES = ("last_value", "random_walk", "drift", "rolling_mean", "ema")
KEY_FIELDS = ("model_identifier", "pair", "origin_id", "target_timestamp", "horizon_step")
OHLC = ("open", "high", "low", "close")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _load_csv(path: Path) -> pd.DataFrame:
    first = path.open(encoding="utf-8").readline()
    df = pd.read_csv(path, sep="\t" if "\t" in first else ",")
    df = df.rename(columns={"<DATE>": "timestamp", "Open": "open", "High": "high",
                            "Low": "low", "Close": "close"})
    required = {"timestamp", *OHLC}
    assert required <= set(df), f"{path}: missing columns {sorted(required - set(df))}"
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    assert df["timestamp"].is_monotonic_increasing, f"{path}: timestamps not chronological"
    assert not df["timestamp"].duplicated().any(), f"{path}: duplicate timestamps"
    assert ((df["high"] >= df[["open", "close", "low"]].max(axis=1)) &
            (df["low"] <= df[["open", "close", "high"]].min(axis=1))).all(), \
        f"{path}: invalid OHLC"
    return df.reset_index(drop=True)


def _settings(config: dict[str, Any]) -> dict[str, Any]:
    forecast = config["forecast"]
    baseline = config["baseline_parameters"]
    return {
        "seed": int(forecast["seed"]),
        "temperature": float(forecast["temperature"]),
        "top_p": float(forecast["top_p"]),
        "sample_count": int(forecast["sample_count"]),
        "context_steps": int(forecast["context_steps"]),
        "horizon": int(forecast["prediction_horizon"]),
        "rolling_window": int(baseline["rolling_mean"]["window"]),
        "ema_span": int(baseline["ema"]["span"]),
        "rw_vol_window": int(baseline["random_walk"]["volatility_window"]),
        "rw_samples": int(baseline["random_walk"]["samples"]),
    }


def _prediction_identity(predictor: Any, mode: str, config: dict[str, Any]) -> dict[str, Any]:
    is_fake = isinstance(predictor, FakeKronosPredictor)
    predictor_type = "fake" if is_fake else "kronos"
    if is_fake and mode != "synthetic_test":
        raise ValueError(f"FakeKronosPredictor is forbidden in execution mode {mode}")
    if not is_fake and mode == "synthetic_test":
        raise ValueError("synthetic_test mode requires FakeKronosPredictor")
    model = config["model"]
    return {
        "execution_mode": mode,
        "predictor_type": predictor_type,
        "predictor_class": type(predictor).__name__,
        "model_identifier": "fake-kronos-deterministic" if is_fake else model["repo"],
        "checkpoint_identifier": "none" if is_fake else model["model_revision"],
        "is_synthetic": is_fake,
        "evidence_eligible": not is_fake,
    }


def _seed_for_origin(seed: int, pair: str, origin_id: str) -> int:
    digest = hashlib.sha256(f"{seed}|{pair}|{origin_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _baselines(context: np.ndarray, horizon: int, settings: dict[str, Any],
               pair: str, origin_id: str) -> dict[str, tuple[np.ndarray, dict[str, Any]]]:
    close = np.asarray(context, dtype=float)
    last = float(close[-1])
    differences = np.diff(close)
    drift = float(differences.mean()) if len(differences) else 0.0
    vol_values = differences[-settings["rw_vol_window"]:]
    volatility = float(vol_values.std(ddof=1)) if len(vol_values) > 1 else 0.0
    rng = np.random.default_rng(_seed_for_origin(settings["seed"], pair, origin_id))
    innovations = rng.normal(0.0, volatility, size=horizon)
    random_walk = last + np.cumsum(innovations)
    rolling = float(close[-settings["rolling_window"]:].mean())
    ema = float(pd.Series(close).ewm(span=settings["ema_span"], adjust=False).mean().iloc[-1])
    return {
        "last_value": (np.full(horizon, last), {}),
        "random_walk": (random_walk, {
            "innovation_distribution": "normal",
            "innovation_mean": 0.0, "volatility_estimator": "sample_std_close_differences",
            "volatility_window": settings["rw_vol_window"], "path_dependent": True,
            "samples": settings["rw_samples"],
            "seed": _seed_for_origin(settings["seed"], pair, origin_id),
        }),
        "drift": (last + drift * np.arange(1, horizon + 1), {
            "drift": "mean_context_close_difference"}),
        "rolling_mean": (np.full(horizon, rolling), {"window": settings["rolling_window"]}),
        "ema": (np.full(horizon, ema), {"span": settings["ema_span"], "adjust": False}),
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("zero prediction rows cannot produce metrics")
    predicted = np.array([r["predicted_close"] for r in rows], dtype=float)
    actual = np.array([r["actual_close"] for r in rows], dtype=float)
    origin = np.array([r["origin_close"] for r in rows], dtype=float)
    close_error = predicted - actual
    scale = np.maximum(np.abs(origin), np.finfo(float).eps)
    valid = np.array([
        r["predicted_high"] >= max(r["predicted_open"], r["predicted_close"]) and
        r["predicted_low"] <= min(r["predicted_open"], r["predicted_close"])
        for r in rows
    ])
    coverage = np.array([
        r["predicted_low"] <= r["actual_low"] and r["predicted_high"] >= r["actual_high"]
        for r in rows
    ])
    return {
        "row_count": len(rows),
        "close_mae": float(np.mean(np.abs(close_error))),
        "close_rmse": float(np.sqrt(np.mean(close_error ** 2))),
        "normalized_close_mae": float(np.mean(np.abs(close_error) / scale)),
        "return_mae": float(np.mean(np.abs(np.log(predicted / origin) - np.log(actual / origin)))),
        "directional_accuracy": float(np.mean(np.sign(predicted-origin) == np.sign(actual-origin))),
        "high_low_interval_coverage": float(coverage.mean()),
        "ohlc_validity_rate": float(valid.mean()),
    }


def _metric_groups(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    per_origin: dict[str, Any] = {}
    per_pair: dict[str, Any] = {}
    for row in rows:
        per_origin.setdefault(row["origin_id"], []).append(row)
        per_pair.setdefault(row["pair"], []).append(row)
    return (
        {key: _metrics(value) for key, value in sorted(per_origin.items())},
        {key: _metrics(value) for key, value in sorted(per_pair.items())},
        _metrics(rows),
    )


def _validate_origin(origin: dict[str, Any], df: pd.DataFrame, split: dict[str, str],
                     settings: dict[str, Any]) -> tuple[int, pd.DataFrame, pd.DataFrame]:
    origin_ts = pd.Timestamp(origin["origin_timestamp"])
    matches = df.index[df["timestamp"] == origin_ts].tolist()
    assert len(matches) == 1, f"{origin['origin_id']}: origin timestamp not unique"
    idx = matches[0]
    context = df.iloc[idx-settings["context_steps"]+1:idx+1]
    target = df.iloc[idx+1:idx+1+settings["horizon"]]
    assert len(context) == settings["context_steps"], f"{origin['origin_id']}: insufficient context"
    assert len(target) == settings["horizon"], f"{origin['origin_id']}: missing forecast rows"
    assert context["timestamp"].max() == origin_ts
    assert context["timestamp"].max() < target["timestamp"].min(), "future-context leakage"
    start, end = pd.Timestamp(split["start"]), pd.Timestamp(split["end"])
    assert target["timestamp"].min() >= start and target["timestamp"].max() <= end, \
        f"{origin['origin_id']}: stage crossover"
    return idx, context, target


def _predict_ohlc(prediction: Any, horizon: int) -> list[dict[str, float]]:
    """Extract OHLC forecasts from predictor output.

    Supports the new KronosPredictionResult contract (preferred)
    and the legacy scalar format for backward compatibility.
    """
    # New contract: KronosPredictionResult with raw_predictions DataFrame
    from engine.kronos_adapter.prediction_result import KronosPredictionResult

    if isinstance(prediction, KronosPredictionResult):
        raw_df = prediction.raw_predictions
        if not isinstance(raw_df, pd.DataFrame) or raw_df.empty:
            raise ValueError("predictor.raw_predictions must be a non-empty DataFrame")
        result = []
        for _, row in raw_df.iterrows():
            result.append({
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        return result

    # Legacy format: dict with horizon_0..horizon_N keys
    expected = [f"horizon_{i}" for i in range(horizon)]
    if not isinstance(prediction, dict) or list(prediction) != expected:
        raise ValueError(f"predictor must return exactly ordered keys {expected}")
    result = []
    for key in expected:
        value = prediction[key]
        if isinstance(value, dict):
            result.append({
                "open": float(value.get("open", value.get("raw_open", 0))),
                "high": float(value.get("high", value.get("raw_high", 0))),
                "low": float(value.get("low", value.get("raw_low", 0))),
                "close": float(value.get("close", value.get("raw_close", 0))),
            })
        else:
            close = float(value)
            result.append({"open": close, "high": close, "low": close, "close": close})
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing empty artifact {path.name}")
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, sort_keys=True, separators=(",", ":"))
                if isinstance(value, (dict, list)) else value for key, value in row.items()
            })


def run_stage(
    mode: str,
    *,
    predictor_factory: Callable[[], Any] | None = None,
    config_path: Path | str = DEFAULT_CONFIG,
    dataset_manifest_path: Path | str = DEFAULT_DATASET_MANIFEST,
    fold_manifest_path: Path | str = DEFAULT_FOLD_MANIFEST,
    origin_manifest_path: Path | str = DEFAULT_ORIGIN_MANIFEST,
    metric_spec_path: Path | str = DEFAULT_METRIC_SPEC,
    output_dir: Path | str = DEFAULT_OUTPUT,
    unseal: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Run one explicitly configured stage and emit deterministic evidence."""
    if mode == "sealed-test":  # backward-compatible spelling
        mode = "sealed_test"
    if mode not in STAGES:
        raise ValueError(f"unknown execution mode: {mode}")
    if mode == "sealed_test" and not unseal:
        raise PermissionError("sealed_test requires explicit unseal authorization")
    paths = [Path(p) for p in (config_path, dataset_manifest_path, fold_manifest_path,
                                origin_manifest_path, metric_spec_path)]
    config, dataset, folds, origins, _metric_spec = map(_read_json, paths)
    settings = _settings(config)
    predictor = (predictor_factory or load_kronos_predictor)()
    identity = _prediction_identity(predictor, mode, config)
    split_name = "test" if mode == "sealed_test" else mode
    fold = folds["folds"][0]
    split = fold["splits"][split_name]
    base = Path(dataset_manifest_path).resolve().parent
    dataframes: dict[str, pd.DataFrame] = {}
    dataset_hashes: dict[str, str] = {}
    for pair, entry in dataset["datasets"].items():
        csv_path = _resolve(base, entry["csv_path"])
        assert csv_path.exists(), f"dataset missing: {csv_path}"
        digest = _sha256(csv_path)
        assert digest == entry["sha256"], f"{pair}: dataset hash mismatch"
        dataframes[pair] = _load_csv(csv_path)
        dataset_hashes[pair] = digest

    selected = [o for o in origins["origins"] if o["stage"] == split_name]
    if not selected:
        raise ValueError(f"zero origins for {split_name}")
    kronos_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    started = datetime.now(timezone.utc).isoformat()
    for origin in selected:
        pair = origin["pair"]
        _, context, target = _validate_origin(origin, dataframes[pair], split, settings)
        # Build explicit timestamps for the new predictor interface
        x_ts = context["timestamp"]
        y_ts = target["timestamp"]
        # Pass only columns that actually exist in the context DataFrame
        ohlc_cols = [c for c in OHLC if c in context.columns]
        context_df = context[ohlc_cols].copy()
        raw = predictor.predict(
            context_df, x_timestamp=x_ts, y_timestamp=y_ts,
            prediction_length=settings["horizon"],
            temperature=settings["temperature"], top_p=settings["top_p"],
            sample_count=settings["sample_count"], seed=settings["seed"],
        )
        forecasts = _predict_ohlc(raw, settings["horizon"])
        base_values = _baselines(context["close"].to_numpy(), settings["horizon"],
                                 settings, pair, origin["origin_id"])
        for step, (forecast, (_, actual)) in enumerate(zip(forecasts, target.iterrows()), 1):
            common = {
                "stage": split_name, **identity, "pair": pair,
                "origin_timestamp": origin["origin_timestamp"],
                "target_timestamp": actual["timestamp"].isoformat(),
                "horizon_step": step,
                "source_row_identifier": f"{dataset_hashes[pair]}:{int(actual.name)}",
                "actual_open": float(actual["open"]), "actual_high": float(actual["high"]),
                "actual_low": float(actual["low"]), "actual_close": float(actual["close"]),
                "origin_close": float(context["close"].iloc[-1]),
                "seed": settings["seed"], "temperature": settings["temperature"],
                "context_steps": settings["context_steps"], "dataset_sha256": dataset_hashes[pair],
                "fold_id": fold["fold_id"], "origin_id": origin["origin_id"],
            }
            kronos_rows.append({
                **common, "predicted_open": forecast["open"], "predicted_high": forecast["high"],
                "predicted_low": forecast["low"], "predicted_close": forecast["close"],
            })
            for name, (values, parameters) in base_values.items():
                value = float(values[step-1])
                baseline_rows.append({
                    **common, "model_identifier": f"baseline:{name}",
                    "checkpoint_identifier": "frozen-config",
                    "predicted_open": value, "predicted_high": value,
                    "predicted_low": value, "predicted_close": value,
                    "baseline_name": name, "baseline_parameters": parameters,
                })

    if len({tuple(row[k] for k in KEY_FIELDS) for row in kronos_rows}) != len(kronos_rows):
        raise ValueError("duplicate prediction key")
    for origin in selected:
        oid = origin["origin_id"]
        if sum(r["origin_id"] == oid for r in kronos_rows) != settings["horizon"]:
            raise ValueError(f"{oid}: incomplete forecast")
        names = {r["baseline_name"] for r in baseline_rows if r["origin_id"] == oid}
        if names != set(BASELINES):
            raise ValueError(f"{oid}: incomplete baseline set")

    per_origin, per_pair, aggregate = _metric_groups(kronos_rows)
    out = Path(output_dir) / mode
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "predictions_kronos.csv", kronos_rows)
    _write_csv(out / "predictions_baselines.csv", baseline_rows)
    _canonical_write(out / "per_origin_metrics.json", per_origin)
    _canonical_write(out / "per_pair_metrics.json", per_pair)
    _canonical_write(out / "aggregate_metrics.json", aggregate)
    _canonical_write(out / "execution_log.json", {
        **identity, "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
        "origin_count": len(selected), "prediction_rows": len(kronos_rows),
        "baseline_rows": len(baseline_rows),
    })
    _canonical_write(out / "environment_manifest.json", {
        **identity, "python": platform.python_version(), "platform": platform.platform(),
        "numpy": np.__version__, "pandas": pd.__version__,
    })
    required = [
        "predictions_kronos.csv", "predictions_baselines.csv", "per_origin_metrics.json",
        "per_pair_metrics.json", "aggregate_metrics.json", "execution_log.json",
        "environment_manifest.json",
    ]
    evidence = {
        **identity, "stage": split_name, "expected_origin_count": len(selected),
        "expected_horizon": settings["horizon"], "baselines": list(BASELINES),
        "files": {name: _sha256(out / name) for name in required},
    }
    _canonical_write(out / "evidence_manifest.json", evidence)
    return {"output_dir": out, "origins": len(selected), "predictions": kronos_rows,
            "baselines": baseline_rows, "aggregate_metrics": aggregate}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=STAGES, required=True)
    parser.add_argument("--predictor-type", choices=("fake", "kronos"), default="kronos")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--fold-manifest", type=Path, default=DEFAULT_FOLD_MANIFEST)
    parser.add_argument("--origin-manifest", type=Path, default=DEFAULT_ORIGIN_MANIFEST)
    parser.add_argument("--metric-spec", type=Path, default=DEFAULT_METRIC_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--unseal", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    factory = FakeKronosPredictor if args.predictor_type == "fake" else load_kronos_predictor
    run_stage(args.mode, predictor_factory=factory, config_path=args.config,
              dataset_manifest_path=args.dataset_manifest, fold_manifest_path=args.fold_manifest,
              origin_manifest_path=args.origin_manifest, metric_spec_path=args.metric_spec,
              output_dir=args.output_dir, unseal=args.unseal)


if __name__ == "__main__":
    main()
