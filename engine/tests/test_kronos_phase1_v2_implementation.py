from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from engine.kronos_adapter import FakeKronosPredictor
from engine.replay_phase1_v2_evidence import replay
from engine.run_phase1_v2_benchmark import BASELINES, run_stage


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


@pytest.fixture
def synthetic_case(tmp_path: Path) -> dict[str, Path]:
    data = tmp_path / "data"
    data.mkdir()
    pairs = ["SYN_A", "SYN_B", "SYN_C", "SYN_D"]
    dates = pd.bdate_range("2024-01-01", periods=80, tz="UTC")
    datasets = {}
    for pair_index, pair in enumerate(pairs):
        close = [1 + pair_index * .2 + i * .001 + ((i % 3) - 1) * .0001
                 for i in range(len(dates))]
        frame = pd.DataFrame({
            "timestamp": dates,
            "open": [v - .0002 for v in close],
            "high": [v + .0005 for v in close],
            "low": [v - .0005 for v in close],
            "close": close,
        })
        path = data / f"{pair}.csv"
        frame.to_csv(path, index=False, lineterminator="\n")
        datasets[pair] = {
            "csv_path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "row_count": len(frame),
        }
    config = {
        "model": {"repo": "synthetic/never-load", "model_revision": "none"},
        "forecast": {"context_steps": 20, "prediction_horizon": 5, "seed": 7,
                     "temperature": 1.0, "top_p": .9, "sample_count": 1},
        "baseline_parameters": {
            "last_value": {},
            "random_walk": {"volatility_window": 10, "samples": 1},
            "drift": {}, "rolling_mean": {"window": 10},
            "ema": {"span": 10},
        },
    }
    folds = {"folds": [{
        "fold_id": "synthetic_fold",
        "splits": {
            "synthetic_test": {
                "start": dates[20].isoformat(), "end": dates[79].isoformat()},
            "development": {
                "start": dates[20].isoformat(), "end": dates[49].isoformat()},
            "validation": {
                "start": dates[50].isoformat(), "end": dates[64].isoformat()},
            "test": {
                "start": dates[65].isoformat(), "end": dates[79].isoformat()},
        },
    }]}
    origins = {"origins": []}
    for pair in pairs:
        for number, idx in enumerate((24, 34)):
            origins["origins"].append({
                "origin_id": f"{pair}-origin-{number}",
                "pair": pair, "stage": "synthetic_test",
                "origin_timestamp": dates[idx].isoformat(),
            })
    paths = {
        "config_path": tmp_path / "config.json",
        "dataset_manifest_path": data / "dataset.json",
        "fold_manifest_path": tmp_path / "folds.json",
        "origin_manifest_path": tmp_path / "origins.json",
        "metric_spec_path": tmp_path / "metrics.json",
        "output_dir": tmp_path / "evidence",
    }
    write_json(paths["config_path"], config)
    write_json(paths["dataset_manifest_path"], {"datasets": datasets})
    write_json(paths["fold_manifest_path"], folds)
    write_json(paths["origin_manifest_path"], origins)
    write_json(paths["metric_spec_path"], {"metric_version": "synthetic-1"})
    return paths


@pytest.fixture
def evidence(synthetic_case: dict[str, Path]) -> dict:
    return run_stage("synthetic_test", predictor_factory=FakeKronosPredictor,
                     **synthetic_case)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def rehash(root: Path, filename: str) -> None:
    manifest_path = root / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][filename] = hashlib.sha256((root / filename).read_bytes()).hexdigest()
    write_json(manifest_path, manifest)


def test_predictor_injection_complete_processing_and_artifacts(evidence: dict) -> None:
    root = evidence["output_dir"]
    assert evidence["origins"] == 8
    assert len(evidence["predictions"]) == 40
    assert len(evidence["baselines"]) == 200
    assert evidence["aggregate_metrics"]["row_count"] == 40
    expected = {
        "predictions_kronos.csv", "predictions_baselines.csv", "per_origin_metrics.json",
        "per_pair_metrics.json", "aggregate_metrics.json", "execution_log.json",
        "environment_manifest.json", "evidence_manifest.json",
    }
    assert expected == {p.name for p in root.iterdir()}


def test_five_distinct_forecast_rows_and_five_baseline_sets(evidence: dict) -> None:
    rows = evidence["predictions"]
    for origin in {r["origin_id"] for r in rows}:
        selected = [r for r in rows if r["origin_id"] == origin]
        assert {r["horizon_step"] for r in selected} == {1, 2, 3, 4, 5}
        assert len({r["target_timestamp"] for r in selected}) == 5
        baseline = [r for r in evidence["baselines"] if r["origin_id"] == origin]
        assert {r["baseline_name"] for r in baseline} == set(BASELINES)
        assert all(sum(r["baseline_name"] == name for r in baseline) == 5 for name in BASELINES)


def test_metadata_separates_synthetic_evidence(evidence: dict) -> None:
    for name in ("execution_log.json", "environment_manifest.json", "evidence_manifest.json"):
        value = json.loads((evidence["output_dir"] / name).read_text())
        assert value["execution_mode"] == "synthetic_test"
        assert value["predictor_type"] == "fake"
        assert value["predictor_class"] == "FakeKronosPredictor"
        assert value["model_identifier"] == "fake-kronos-deterministic"
        assert value["is_synthetic"] is True
        assert value["evidence_eligible"] is False


@pytest.mark.parametrize("mode", ["development", "validation", "sealed_test"])
def test_fake_predictor_rejected_in_real_modes(
    synthetic_case: dict[str, Path], mode: str
) -> None:
    with pytest.raises((ValueError, PermissionError)):
        run_stage(mode, predictor_factory=FakeKronosPredictor,
                  unseal=mode == "sealed_test", **synthetic_case)


class BadPredictor(FakeKronosPredictor):
    def __init__(self, value: dict):
        self.value = value
    def predict(self, *_: object, **__: object) -> dict:
        return self.value


@pytest.mark.parametrize("value", [
    {f"horizon_{i}": 1.0 for i in range(4)},
    {"horizon_0": 1.0, "horizon_1": 1.0, "horizon_2": 1.0,
     "horizon_3": 1.0, "horizon_3_duplicate": 1.0},
    {f"horizon_{i}": {"open": 1, "high": 1, "low": 1} for i in range(5)},
])
def test_missing_duplicate_and_target_mapping_rejected(
    synthetic_case: dict[str, Path], value: dict
) -> None:
    with pytest.raises(ValueError):
        run_stage("synthetic_test", predictor_factory=lambda: BadPredictor(value),
                  **synthetic_case)


def test_future_context_leakage_and_stage_crossover_rejected(
    synthetic_case: dict[str, Path]
) -> None:
    folds = json.loads(synthetic_case["fold_manifest_path"].read_text())
    folds["folds"][0]["splits"]["synthetic_test"]["end"] = "2024-02-06T00:00:00+00:00"
    write_json(synthetic_case["fold_manifest_path"], folds)
    with pytest.raises(AssertionError, match="stage crossover"):
        run_stage("synthetic_test", predictor_factory=FakeKronosPredictor,
                  **synthetic_case)


def test_incomplete_baseline_rejected(monkeypatch: pytest.MonkeyPatch,
                                      synthetic_case: dict[str, Path]) -> None:
    import engine.run_phase1_v2_benchmark as runner
    original = runner._baselines
    def incomplete(*args: object, **kwargs: object) -> dict:
        value = original(*args, **kwargs)
        value.pop("ema")
        return value
    monkeypatch.setattr(runner, "_baselines", incomplete)
    with pytest.raises(ValueError, match="incomplete baseline"):
        run_stage("synthetic_test", predictor_factory=FakeKronosPredictor,
                  **synthetic_case)


def test_metric_replay_and_synthetic_real_stage_rejection(evidence: dict) -> None:
    assert replay(evidence["output_dir"])["row_count"] == 40
    with pytest.raises(ValueError, match="synthetic evidence"):
        replay(evidence["output_dir"], real_stage=True)


def test_prediction_tamper_detection(evidence: dict) -> None:
    path = evidence["output_dir"] / "predictions_kronos.csv"
    path.write_text(path.read_text().replace("1.0248", "9.0248", 1))
    with pytest.raises(ValueError, match="hash-mismatched"):
        replay(evidence["output_dir"])


@pytest.mark.parametrize("mutation", ["delete", "duplicate"])
def test_deletion_or_duplication_rejected(evidence: dict, mutation: str) -> None:
    root = evidence["output_dir"]
    path = root / "predictions_kronos.csv"
    lines = path.read_text().splitlines()
    if mutation == "delete":
        lines.pop()
    else:
        lines.append(lines[-1])
    path.write_text("\n".join(lines) + "\n")
    rehash(root, path.name)
    with pytest.raises(ValueError):
        replay(root)


def test_zero_metric_exit_rejected() -> None:
    from engine.run_phase1_v2_benchmark import _metrics
    with pytest.raises(ValueError, match="zero prediction"):
        _metrics([])


def test_replay_process_has_no_torch_or_transformers(evidence: dict) -> None:
    code = (
        "import sys;"
        "from engine.replay_phase1_v2_evidence import replay;"
        f"replay({str(evidence['output_dir'])!r});"
        "assert 'torch' not in sys.modules and 'transformers' not in sys.modules;"
        "print('OFFLINE_REPLAY_OK')"
    )
    result = subprocess.run([sys.executable, "-c", code], text=True,
                            capture_output=True, check=True)
    assert result.stdout.strip() == "OFFLINE_REPLAY_OK"
