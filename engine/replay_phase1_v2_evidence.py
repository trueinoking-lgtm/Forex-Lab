"""Offline Kronos evidence replay. This module intentionally imports no ML stack."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

BASELINES = {"last_value", "random_walk", "drift", "rolling_mean", "ema"}
KEY = ("model_identifier", "pair", "origin_id", "target_timestamp", "horizon_step")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    numeric = {
        "horizon_step", "predicted_open", "predicted_high", "predicted_low",
        "predicted_close", "actual_open", "actual_high", "actual_low", "actual_close",
        "origin_close", "seed", "temperature", "context_steps",
    }
    for row in rows:
        for field in numeric:
            row[field] = int(row[field]) if field in {"horizon_step", "seed", "context_steps"} \
                else float(row[field])
    return rows


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("empty prediction evidence")
    errors = [r["predicted_close"] - r["actual_close"] for r in rows]
    return {
        "row_count": len(rows),
        "close_mae": sum(abs(x) for x in errors) / len(rows),
        "close_rmse": math.sqrt(sum(x*x for x in errors) / len(rows)),
        "normalized_close_mae": sum(
            abs(e) / max(abs(r["origin_close"]), sys.float_info.epsilon)
            for e, r in zip(errors, rows)) / len(rows),
        "return_mae": sum(abs(math.log(r["predicted_close"]/r["origin_close"]) -
                              math.log(r["actual_close"]/r["origin_close"]))
                          for r in rows) / len(rows),
        "directional_accuracy": sum(
            (r["predicted_close"]-r["origin_close"] >= 0) ==
            (r["actual_close"]-r["origin_close"] >= 0) for r in rows) / len(rows),
        "high_low_interval_coverage": sum(
            r["predicted_low"] <= r["actual_low"] and
            r["predicted_high"] >= r["actual_high"] for r in rows) / len(rows),
        "ohlc_validity_rate": sum(
            r["predicted_high"] >= max(r["predicted_open"], r["predicted_close"]) and
            r["predicted_low"] <= min(r["predicted_open"], r["predicted_close"])
            for r in rows) / len(rows),
    }


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, (float, int)) and isinstance(right, (float, int)):
        return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)
    return left == right


def replay(evidence_dir: Path | str, *, real_stage: bool = False) -> dict[str, Any]:
    root = Path(evidence_dir)
    manifest_path = root / "evidence_manifest.json"
    if not manifest_path.exists():
        raise ValueError("missing evidence_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if real_stage and (manifest.get("is_synthetic") or not manifest.get("evidence_eligible")):
        raise PermissionError("synthetic evidence is not eligible for real-stage verification")
    for name, digest in manifest["files"].items():
        path = root / name
        if not path.exists() or _sha(path) != digest:
            raise ValueError(f"missing or hash-mismatched evidence file: {name}")
    rows = _load_rows(root / "predictions_kronos.csv")
    baselines = _load_rows(root / "predictions_baselines.csv")
    keys = [tuple(str(row[k]) for k in KEY) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate prediction key")
    origins = {r["origin_id"] for r in rows}
    if len(origins) != manifest["expected_origin_count"]:
        raise ValueError("unexpected origin count")
    horizon = manifest["expected_horizon"]
    for origin in origins:
        subset = [r for r in rows if r["origin_id"] == origin]
        if len(subset) != horizon or {r["horizon_step"] for r in subset} != set(range(1, horizon+1)):
            raise ValueError(f"{origin}: missing, duplicate, or invalid horizon row")
        baseline_subset = [r for r in baselines if r["origin_id"] == origin]
        if {r["baseline_name"] for r in baseline_subset} != BASELINES:
            raise ValueError(f"{origin}: incomplete baseline set")
        if len(baseline_subset) != horizon * len(BASELINES):
            raise ValueError(f"{origin}: missing or duplicate baseline row")
    per_origin = {origin: _metrics([r for r in rows if r["origin_id"] == origin])
                  for origin in sorted(origins)}
    pairs = {r["pair"] for r in rows}
    per_pair = {pair: _metrics([r for r in rows if r["pair"] == pair])
                for pair in sorted(pairs)}
    aggregate = _metrics(rows)
    recorded = [
        json.loads((root / "per_origin_metrics.json").read_text()),
        json.loads((root / "per_pair_metrics.json").read_text()),
        json.loads((root / "aggregate_metrics.json").read_text()),
    ]
    if not all(_equal(a, b) for a, b in zip((per_origin, per_pair, aggregate), recorded)):
        raise ValueError("recorded metrics do not match independent replay")
    forbidden = [name for name in sys.modules if name == "torch" or name.startswith("torch.") or
                 name == "transformers" or name.startswith("transformers.")]
    if forbidden:
        raise RuntimeError(f"offline replay imported forbidden modules: {forbidden}")
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_dir", type=Path)
    parser.add_argument("--real-stage", action="store_true")
    args = parser.parse_args()
    replay(args.evidence_dir, real_stage=args.real_stage)
    print("REPLAY_OK")


if __name__ == "__main__":
    main()
