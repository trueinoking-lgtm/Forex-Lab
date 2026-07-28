from __future__ import annotations

import ast
import inspect
import textwrap

import numpy as np
import pandas as pd
import pytest

import engine.kronos_adapter.model_src.kronos as vendored
from engine.kronos_adapter.predictor import FakeKronosPredictor, KronosPredictor


def fixture(with_volume: bool = False) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    x_timestamp = pd.Series(pd.date_range("2025-01-01", periods=50, freq="D", tz="UTC"))
    y_timestamp = pd.Series(pd.date_range("2025-02-20", periods=5, freq="D", tz="UTC"))
    close = 100 + np.arange(50) * 0.1 + np.sin(np.arange(50) / 3)
    frame = pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
        }
    )
    if with_volume:
        frame["volume"] = 1000 + np.arange(50)
        frame["amount"] = frame["volume"] * close
    return frame, x_timestamp, y_timestamp


class OfficialSpy:
    calls: list[dict] = []

    def __init__(self, model, tokenizer, device=None):
        self.model = model
        self.tokenizer = tokenizer
        self.device = device

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        df = kwargs["df"]
        result = pd.DataFrame(
            {
                "open": np.full(5, float(df["close"].iloc[-1])),
                "high": np.full(5, float(df["close"].iloc[-1]) + 1),
                "low": np.full(5, float(df["close"].iloc[-1]) - 1),
                "close": np.full(5, float(df["close"].iloc[-1])),
            },
            index=pd.Index(kwargs["y_timestamp"]),
        )
        return result

    def generate(self, *args, **kwargs):
        raise AssertionError("outer adapter called generate directly")


def ready_predictor() -> KronosPredictor:
    predictor = KronosPredictor()
    predictor._loaded = True
    predictor._model = object()
    predictor._tokenizer = object()
    return predictor


def test_adapter_calls_official_predict_and_never_generate(monkeypatch):
    frame, x_timestamp, y_timestamp = fixture()
    OfficialSpy.calls.clear()
    monkeypatch.setattr(vendored, "KronosPredictor", OfficialSpy)
    monkeypatch.setattr(
        vendored,
        "auto_regressive_inference",
        lambda *args, **kwargs: pytest.fail("outer adapter called auto_regressive_inference"),
    )
    result = ready_predictor().predict(
        frame, x_timestamp, y_timestamp, 5, 7, 1.0, 0.9, 1
    )
    assert len(OfficialSpy.calls) == 1
    call = OfficialSpy.calls[0]
    assert call["df"] is frame
    assert call["x_timestamp"].equals(x_timestamp)
    assert call["y_timestamp"].equals(y_timestamp)
    assert call["pred_len"] == 5
    assert call["T"] == 1.0
    assert call["top_p"] == 0.9
    assert call["sample_count"] == 1
    assert call["verbose"] is False
    assert len(result.raw_predictions) == 5
    assert result.raw_predictions.index.equals(pd.Index(y_timestamp))


def test_outer_predict_ast_has_no_forbidden_direct_calls():
    tree = ast.parse(textwrap.dedent(inspect.getsource(KronosPredictor.predict)))
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "generate" not in attributes
    assert "auto_regressive_inference" not in names
    assert "to_numpy" not in attributes


def test_explicit_timestamps_are_required():
    frame, _, _ = fixture()
    with pytest.raises(TypeError):
        ready_predictor().predict(frame, prediction_length=5)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda x, y: (x.iloc[:-1], y), "x_timestamp length"),
        (lambda x, y: (x, y.iloc[:-1]), "y_timestamp length"),
        (lambda x, y: (x, pd.Series([x.iloc[-1], *y.iloc[1:]])), "earlier"),
    ],
)
def test_invalid_timestamp_boundaries_fail_before_loading(mutate, match):
    frame, x_timestamp, y_timestamp = fixture()
    x_timestamp, y_timestamp = mutate(x_timestamp, y_timestamp)
    with pytest.raises(ValueError, match=match):
        KronosPredictor().predict(frame, x_timestamp, y_timestamp, 5)


def test_invalid_official_ohlc_fails_closed(monkeypatch):
    frame, x_timestamp, y_timestamp = fixture()

    class InvalidOfficial(OfficialSpy):
        def predict(self, **kwargs):
            result = super().predict(**kwargs)
            result.iloc[0, result.columns.get_loc("high")] = result.iloc[0]["close"] - 1
            return result

    monkeypatch.setattr(vendored, "KronosPredictor", InvalidOfficial)
    with pytest.raises(ValueError, match="structurally invalid OHLC"):
        ready_predictor().predict(frame, x_timestamp, y_timestamp, 5)


@pytest.mark.parametrize("with_volume", [False, True])
def test_fake_predictor_same_interface_and_ineligible(with_volume):
    frame, x_timestamp, y_timestamp = fixture(with_volume)
    result = FakeKronosPredictor().predict(
        frame, x_timestamp, y_timestamp, 5, 7, 1.0, 0.9, 1
    )
    assert len(result.raw_predictions) == 5
    assert result.raw_predictions.index.equals(pd.Index(y_timestamp))
    assert result.predictor_identity["is_synthetic"] is True
    assert result.predictor_identity["evidence_eligible"] is False
