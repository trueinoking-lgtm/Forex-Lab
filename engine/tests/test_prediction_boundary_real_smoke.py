from __future__ import annotations

import pytest

from engine.run_prediction_boundary_smoke import run


@pytest.mark.parametrize(
    ("with_volume", "expected_shape"),
    [(False, [50, 4]), (True, [50, 6])],
    ids=("ohlc-only", "ohlcv"),
)
def test_real_kronos_synthetic_smoke(with_volume, expected_shape):
    report = run(with_volume)
    assert report["predictor_type"] == "kronos"
    assert report["execution_mode"] == "synthetic_test"
    assert report["is_synthetic"] is True
    assert report["evidence_eligible"] is False
    assert report["input_dataframe_shape"] == expected_shape
    assert report["x_timestamp_shape"] == [50]
    assert report["y_timestamp_shape"] == [5]
    assert report["output_shape"][0] == 5
    assert report["output_index"] == [
        "2025-02-20T00:00:00+00:00",
        "2025-02-21T00:00:00+00:00",
        "2025-02-22T00:00:00+00:00",
        "2025-02-23T00:00:00+00:00",
        "2025-02-24T00:00:00+00:00",
    ]
    assert report["nan_inf_check"] is True
    assert report["ohlc_validity"] is True
    assert report["exit_code"] == 0
