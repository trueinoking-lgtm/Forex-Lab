import pandas as pd
try:
    from engine.src.canonical_eval import evaluate_strategy_canonical, gate_outcomes
    from engine.src.experiment_registry import gate_outcomes as registry_gates
except ModuleNotFoundError:
    from src.canonical_eval import evaluate_strategy_canonical, gate_outcomes
    from src.experiment_registry import gate_outcomes as registry_gates

def test_gate_paths_identical_and_locked():
    values = {"score": 40, "robustness": .3, "oos_return": .01, "profit_factor": 1.3}
    assert gate_outcomes(values) == registry_gates(values)
    assert all(gate_outcomes(values).values())

def test_identical_input_is_identical():
    p = pd.Series(range(100, 500), index=pd.date_range("2020-01-01", periods=400, tz="UTC"), dtype=float)
    fn = lambda x: pd.Series(1., index=x.index)
    ctx = {"walk_forward":{"train_days":100,"test_days":30,"step_days":30}, "cost_bps":3,
           "initial_capital":10000,"periods_per_year":252,"risk_free_rate":0,"min_trades":1}
    a = evaluate_strategy_canonical(p, fn, ctx, strategy="x", symbol="X")
    b = evaluate_strategy_canonical(p, fn, ctx, strategy="x", symbol="X")
    for key in ("lifecycle_metrics", "gates", "rejection_reasons", "eligible"):
        assert a[key] == b[key]
