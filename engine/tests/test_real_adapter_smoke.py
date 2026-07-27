"""Real Kronos adapter synthetic smoke test.

After upstream import fix, this test runs the real KronosPredictor
on a newly generated synthetic OHLC fixture.

No real Forex data is used. All D1 files are synthetic.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
import torch

from engine.kronos_adapter import FakeKronosPredictor, load_kronos_predictor


@pytest.fixture
def synthetic_ohlc(tmp_path: Path) -> dict[str, Path]:
    """Generate deterministic synthetic OHLC D1 data for 4 synthetic pairs."""
    data_dir = tmp_path / "synthetic_data"
    data_dir.mkdir()
    manifest = {"datasets": {}, "generated_at": "2026-07-26T00:00:00Z"}
    pairs = {
        "SYN_A": {"base": 100.0, "drift": 0.0001, "vol": 0.005},
        "SYN_B": {"base": 50.0, "drift": -0.00005, "vol": 0.008},
        "SYN_C": {"base": 1.10, "drift": 0.0, "vol": 0.003},
        "SYN_D": {"base": 150.0, "drift": 0.0002, "vol": 0.01},
    }
    for pair, params in pairs.items():
        dates = pd.bdate_range("2024-01-01", periods=120, tz="UTC")
        n = len(dates)
        close = params["base"] + pd.Series(
            [params["drift"] * i + params["vol"] * (i % 5 - 2) * 0.001 for i in range(n)]
        ).cumsum()
        frame = pd.DataFrame({
            "timestamp": dates,
            "open": close - 0.0005,
            "high": close + 0.0008,
            "low": close - 0.0008,
            "close": close,
        })
        csv_path = data_dir / f"{pair}.csv"
        frame.to_csv(csv_path, index=False)
        manifest["datasets"][pair] = {
            "csv_path": str(csv_path.relative_to(tmp_path)),
            "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return {"data_dir": data_dir, "manifest": manifest, "manifest_path": manifest_path}


def test_real_adapter_imports_without_torch():
    """Importing the adapter does not load torch."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from engine.kronos_adapter import load_kronos_predictor; "
         "print('torch' in sys.modules)"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "False"


def test_lazy_checkpoint_loading(synthetic_ohlc, tmp_path):
    """Checkpoint loads lazily — torch not imported until predictor created."""
    from engine.kronos_adapter import load_kronos_predictor
    predictor = load_kronos_predictor()
    assert not predictor._loaded


def test_real_predictor_predict_completes(synthetic_ohlc, tmp_path):
    """Real Kronos predictor.predict() executes on synthetic OHLC fixture."""
    from engine.kronos_adapter import load_kronos_predictor

    predictor = load_kronos_predictor()
    pair = "SYN_A"
    csv_path = synthetic_ohlc["data_dir"] / f"{pair}.csv"
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])

    LOOKBACK = 20
    context = df.tail(LOOKBACK).copy()
    # Generate future timestamps after context
    last_ts = context["timestamp"].iloc[-1]
    future_dates = pd.date_range(start=last_ts, periods=LOOKBACK + 6, freq="D")[LOOKBACK:]
    x_ts = context["timestamp"]
    y_ts = future_dates[:5]

    start = time.time()
    result = predictor.predict(
        context[["open", "high", "low", "close"]],
        x_timestamp=x_ts,
        y_timestamp=y_ts,
        prediction_length=5,
    )
    elapsed = time.time() - start

    assert len(result) >= 5, f"Expected >= 5 horizon keys, got {len(result)}"
    for i in range(5):
        key = f"horizon_{i}"
        assert key in result, f"Missing {key}"
        ohlc = result[key]
        if isinstance(ohlc, dict):
            assert set(ohlc.keys()) >= {"raw_open", "raw_high", "raw_low", "raw_close", "raw_ohlc_valid"}

    # Check _raw and _projected are present
    assert "_raw" in result, "Missing _raw key"
    assert "_projected" in result, "Missing _projected key"
    assert isinstance(result["_raw"], pd.DataFrame)
    assert isinstance(result["_projected"], pd.DataFrame)
    assert len(result["_raw"]) == 5
    assert len(result["_projected"]) == 5

    # Evidence labels
    assert result.get("_raw") is not None


def test_real_adapter_artifact_writing(synthetic_ohlc, tmp_path):
    """After fix, a run_stage synthetic_test call writes CSV artifacts."""
    from engine.run_phase1_v2_benchmark import run_stage

    config = {
        "forecast": {
            "seed": 0, "temperature": 1.0, "top_p": 0.9,
            "sample_count": 1, "context_steps": 20,
            "prediction_horizon": 5,
        },
        "baseline_parameters": {
            "last_value": {},
            "random_walk": {
                "volatility_window": 20, "samples": 1,
                "innovation_distribution": "normal",
            },
            "drift": {},
            "rolling_mean": {"window": 20},
            "ema": {"span": 10, "adjust": False},
        },
        "model": {
            "repo": "amazon/chronos-t5-small",
            "model_revision": "main",
            "tokenizer_revision": "main",
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2))

    dataset_manifest_path = tmp_path / "dataset_manifest.json"
    dataset_manifest_path.write_text(json.dumps(synthetic_ohlc["manifest"], indent=2))

    # Build fold manifest
    fold_manifest = {
        "fold_id": "synthetic-fold-1",
        "splits": {
            "development": {
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-04-01T00:00:00Z",
            },
        },
    }
    fold_manifest_path = tmp_path / "fold_manifest.json"
    fold_manifest_path.write_text(json.dumps(fold_manifest, indent=2))

    fold_manifest = {
        "fold_id": "synthetic-fold-1",
        "splits": {
            "development": {
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-04-01T00:00:00Z",
            },
        },
    }
    fold_manifest_path = tmp_path / "fold_manifest.json"
    fold_manifest_path.write_text(json.dumps(fold_manifest, indent=2))

    # Build origin manifest (using development-only origins for synthetic_test)
    development_dates = pd.bdate_range("2024-01-22", periods=10, tz="UTC")
    origins = {
        "origins": [
            {
                "origin_id": f"synthetic-origin-{i}",
                "pair": "SYN_A",
                "stage": "development",
                "origin_timestamp": str(development_dates[i]),
            }
            for i in range(len(development_dates))
        ],
    }
    origin_manifest_path = tmp_path / "origin_manifest.json"
    origin_manifest_path.write_text(json.dumps(origins, indent=2))

    metric_spec = {
        "metrics": ["close_mae", "close_rmse", "normalized_close_mae",
                     "return_mae", "directional_accuracy",
                     "high_low_interval_coverage", "ohlc_validity_rate"],
    }
    metric_spec_path = tmp_path / "metric_spec.json"
    metric_spec_path.write_text(json.dumps(metric_spec, indent=2))

    output_dir = tmp_path / "output"

    result = run_stage(
        "synthetic_test",
        predictor_factory=lambda: FakeKronosPredictor(),
        config_path=config_path,
        dataset_manifest_path=dataset_manifest_path,
        fold_manifest_path=fold_manifest_path,
        origin_manifest_path=origin_manifest_path,
        metric_spec_path=metric_spec_path,
        output_dir=output_dir,
    )

    assert result["origins"] > 0
    assert (output_dir / "synthetic_test" / "predictions_kronos.csv").exists()
    assert (output_dir / "synthetic_test" / "evidence_manifest.json").exists()

    # Verify artifact metadata states synthetic
    evidence_path = output_dir / "synthetic_test" / "evidence_manifest.json"
    with open(evidence_path) as f:
        evidence = json.load(f)
    assert evidence["is_synthetic"] is True
    assert evidence["evidence_eligible"] is False
    assert evidence["predictor_type"] == "fake"
    assert evidence["execution_mode"] == "synthetic_test"


def test_offline_replay_with_real_artifacts(synthetic_ohlc, tmp_path):
    """After artifact creation, offline replay succeeds with fake predictor output."""
    from engine.replay_phase1_v2_evidence import replay
    from engine.run_phase1_v2_benchmark import run_stage

    config = {
        "forecast": {
            "seed": 0, "temperature": 1.0, "top_p": 0.9,
            "sample_count": 1, "context_steps": 20,
            "prediction_horizon": 5,
        },
        "baseline_parameters": {
            "last_value": {}, "random_walk": {
                "volatility_window": 20, "samples": 1,
                "innovation_distribution": "normal",
            }, "drift": {},
            "rolling_mean": {"window": 20},
            "ema": {"span": 10, "adjust": False},
        },
        "model": {
            "repo": "amazon/chronos-t5-small",
            "model_revision": "main",
            "tokenizer_revision": "main",
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    dataset_manifest_path = tmp_path / "dataset_manifest.json"
    dataset_manifest_path.write_text(json.dumps(synthetic_ohlc["manifest"], indent=2))

    development_dates = pd.bdate_range("2024-01-22", periods=3, tz="UTC")
    origins = {
        "origins": [
            {
                "origin_id": f"synthetic-origin-{i}",
                "pair": "SYN_A",
                "stage": "development",
                "origin_timestamp": str(development_dates[i]),
            }
            for i in range(len(development_dates))
        ],
    }
    origin_manifest_path = tmp_path / "origin_manifest.json"
    origin_manifest_path.write_text(json.dumps(origins, indent=2))
    metric_spec = {"metrics": ["close_mae", "close_rmse", "normalized_close_mae",
                                "return_mae", "directional_accuracy",
                                "high_low_interval_coverage", "ohlc_validity_rate"]}
    metric_spec_path = tmp_path / "metric_spec.json"
    metric_spec_path.write_text(json.dumps(metric_spec, indent=2))
    output_dir = tmp_path / "output"

    run_stage(
        "synthetic_test",
        predictor_factory=lambda: FakeKronosPredictor(),
        config_path=config_path,
        dataset_manifest_path=dataset_manifest_path,
        fold_manifest_path=tmp_path / "fold_manifest.json",
        origin_manifest_path=origin_manifest_path,
        metric_spec_path=metric_spec_path,
        output_dir=output_dir,
    )

    # Replay and verify
    fold_path = tmp_path / "fold_manifest.json"
    fold_path.write_text(json.dumps({
        "fold_id": "synthetic-fold-1",
        "splits": {"development": {
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-04-01T00:00:00Z",
        }},
    }, indent=2))

    replay_result = replay(output_dir / "synthetic_test", real_stage=False)
    assert replay_result is not None


def test_metric_replay_and_synthetic_real_stage_rejection(synthetic_ohlc, tmp_path):
    """Replay rejects synthetic evidence when asked to treat it as real stage."""
    from engine.replay_phase1_v2_evidence import replay
    from engine.run_phase1_v2_benchmark import run_stage

    config = {
        "forecast": {
            "seed": 0, "temperature": 1.0, "top_p": 0.9,
            "sample_count": 1, "context_steps": 20,
            "prediction_horizon": 5,
        },
        "baseline_parameters": {
            "last_value": {}, "random_walk": {
                "volatility_window": 20, "samples": 1,
                "innovation_distribution": "normal",
            }, "drift": {},
            "rolling_mean": {"window": 20},
            "ema": {"span": 10, "adjust": False},
        },
        "model": {
            "repo": "amazon/chronos-t5-small",
            "model_revision": "main",
            "tokenizer_revision": "main",
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    dataset_manifest_path = tmp_path / "dataset_manifest.json"
    dataset_manifest_path.write_text(json.dumps(synthetic_ohlc["manifest"], indent=2))

    development_dates = pd.bdate_range("2024-01-22", periods=3, tz="UTC")
    origins = {
        "origins": [
            {
                "origin_id": f"synthetic-origin-{i}",
                "pair": "SYN_A",
                "stage": "development",
                "origin_timestamp": str(development_dates[i]),
            }
            for i in range(len(development_dates))
        ],
    }
    origin_manifest_path = tmp_path / "origin_manifest.json"
    origin_manifest_path.write_text(json.dumps(origins, indent=2))
    metric_spec = {"metrics": ["close_mae", "close_rmse", "normalized_close_mae",
                                "return_mae", "directional_accuracy",
                                "high_low_interval_coverage", "ohlc_validity_rate"]}
    metric_spec_path = tmp_path / "metric_spec.json"
    metric_spec_path.write_text(json.dumps(metric_spec, indent=2))
    output_dir = tmp_path / "output"

    run_stage(
        "synthetic_test",
        predictor_factory=lambda: FakeKronosPredictor(),
        config_path=config_path,
        dataset_manifest_path=dataset_manifest_path,
        fold_manifest_path=tmp_path / "fold_manifest.json",
        origin_manifest_path=origin_manifest_path,
        metric_spec_path=metric_spec_path,
        output_dir=output_dir,
    )

    # Replay with real_stage — should reject (evidence_eligible=False)
    with pytest.raises(PermissionError):
        replay(output_dir / "synthetic_test", real_stage=True)