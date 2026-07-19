import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.experiment_registry import build_experiment, canonical_json, register_experiment


def payload(metrics=None):
    return {
        "git_commit_hash": "a" * 40,
        "strategy_name": "ema_crossover",
        "strategy_parameters": {"slow": 26, "fast": 12},
        "symbol": "EURUSD=X", "timeframe": "1d", "data_source": "fixture",
        "data_fingerprint": "b" * 64,
        "date_range": {"start": "2024-01-01", "end": "2025-01-01"},
        "boundaries": {"train": "2024-06-01", "validation": "2024-09-01",
                       "oos": "2024-11-01"},
        "spread_bps": 2, "slippage_bps": 1, "commission_bps": 0,
        "random_seed": None, "trade_count": 30,
        "performance_metrics": metrics or {
            "total_return": .08, "max_drawdown": -.03, "profit_factor": 1.5,
            "win_rate": .55, "trade_count": 30, "score": 50,
            "robustness": .4, "oos_return": .05, "sharpe": .7,
        },
        "artifact_paths": ["results/backtest_EURUSDX.json"],
    }


def test_serialization_is_strict_json_and_emits_markdown(tmp_path):
    store, markdown = tmp_path / "registry.json", tmp_path / "registry.md"
    record = register_experiment(payload(), store, markdown,
                                 created_at="2026-07-19T00:00:00Z")
    decoded = json.loads(store.read_text())
    assert decoded["experiments"] == [record]
    assert record["final_status"] == "watcher_eligible"
    assert record["experiment_id"] in markdown.read_text()
    assert "NaN" not in store.read_text()


def test_same_inputs_have_same_id_json_and_append_once(tmp_path):
    first = build_experiment(payload(), created_at="2026-07-19T00:00:00Z")
    second = build_experiment(payload(), created_at="2026-07-19T00:00:00Z")
    assert first["experiment_id"] == second["experiment_id"]
    assert canonical_json(first) == canonical_json(second)
    store = tmp_path / "registry.json"
    saved = register_experiment(payload(), store, created_at="2026-07-19T00:00:00Z")
    again = register_experiment(payload(), store, created_at="2027-01-01T00:00:00Z")
    assert again == saved
    assert len(json.loads(store.read_text())["experiments"]) == 1


def test_incomplete_result_fails_closed(tmp_path):
    incomplete = payload({"trade_count": 3, "score": 99})
    record = register_experiment(incomplete, tmp_path / "registry.json",
                                 created_at="2026-07-19T00:00:00Z")
    assert record["final_status"] == "rejected"
    assert not all(record["execution_gate_outcomes"].values())
    assert any("incomplete result" in reason for reason in record["rejection_reasons"])


def test_secret_shaped_fields_are_rejected():
    unsafe = payload()
    unsafe["api_token"] = "must-not-be-written"
    with pytest.raises(ValueError, match="secret-shaped"):
        build_experiment(unsafe)


def test_non_finite_metric_serializes_as_incomplete(tmp_path):
    values = payload()["performance_metrics"]
    values["profit_factor"] = float("inf")
    record = register_experiment(payload(values), tmp_path / "registry.json",
                                 created_at="2026-07-19T00:00:00Z")
    assert record["performance_metrics"]["profit_factor"] is None
    assert record["final_status"] == "rejected"
