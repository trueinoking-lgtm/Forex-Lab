import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.accounting import (accounting_metadata, legacy_metadata, read_result_artifact,
                            warn_if_accounting_mismatch)
from src.experiment_registry import build_experiment


def _payload(meta):
    return {**meta, "strategy_name": "ema_crossover", "data_fingerprint": "a" * 64,
            "strategy_parameters": {"fast": 12, "slow": 26},
            "performance_metrics": {"total_return": -.1, "max_drawdown": -.2,
              "profit_factor": .8, "win_rate": .4, "trade_count": 20,
              "score": 10, "robustness": 0, "oos_return": -.1}}


def test_accounting_version_changes_experiment_identity():
    corrected = build_experiment(_payload(accounting_metadata(has_explicit_stop=False)))
    legacy = build_experiment(_payload(legacy_metadata()))
    assert corrected["experiment_id"] != legacy["experiment_id"]


def test_results_cannot_load_without_accounting_version():
    with pytest.raises(ValueError, match="without an accounting version"):
        read_result_artifact({"result": 1})


def test_legacy_artifacts_remain_readable_with_warning():
    with pytest.warns(UserWarning, match="legacy artifact"):
        result = read_result_artifact({"result": 1}, allow_legacy=True)
    assert result["accounting_version"] == 1


def test_corrected_cannot_be_mistaken_for_legacy_and_comparison_warns():
    corrected = read_result_artifact(accounting_metadata(has_explicit_stop=True))
    assert corrected["accounting_version"] == 2
    with pytest.warns(UserWarning, match="accounting version mismatch"):
        assert warn_if_accounting_mismatch(corrected, legacy_metadata())


def test_capital_models_distinguish_stop_and_no_stop_strategies():
    assert accounting_metadata(has_explicit_stop=True)["capital_allocation_model"] == "normalized_equal_risk"
    assert accounting_metadata(has_explicit_stop=False)["capital_allocation_model"] == "fixed_notional_fixed_exposure"
