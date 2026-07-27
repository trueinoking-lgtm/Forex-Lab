"""Structural stress test runner for Kronos Phase 1 V2.

Produces stress_run_N.json and stress_run_N_predictions.csv for each run.
Uses real KronosPredictor (NOT FakeKronosPredictor).
"""
import sys, os, json, time, subprocess, hashlib, resource
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from pathlib import Path

RUN_ID = sys.argv[1]  # "run1" or "run2"
OUTPUT_DIR = Path(sys.argv[2])
SEED = 20260725
TEMPERATURE = 1.0
TOP_P = 0.9
SAMPLE_COUNT = 1
PREDICTION_LENGTH = 5
CHECKPOINT_SHA = "a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c"
MODEL_REPO = "NeoQuasar/Kronos-mini"
MODEL_REVISION = "f4e68697d9d5aed55cef5c96aabc3376bcad9f81"
TOKENIZER_REPO = "NeoQuasar/Kronos-Tokenizer-2k"
TOKENIZER_REVISION = "26966d0035065a0cae0ebad7af8ece35bc1fb51c"
OHLC_CONTEXTS = 100
OHLCV_CONTEXTS = 100
TOTAL_CONTEXTS = OHLC_CONTEXTS + OHLCV_CONTEXTS

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Determine tokenizer SHA-256 ──
tokenizer_dir = Path("engine/docs/checkpoints/tokenizer")
tokenizer_files = sorted(tokenizer_dir.glob("*"))
tokenizer_bytes = b""
for fp in tokenizer_files:
    if fp.is_file():
        tokenizer_bytes += fp.read_bytes()
TOKENIZER_SHA = hashlib.sha256(tokenizer_bytes).hexdigest()

# ── Generate deterministic contexts ──
def make_ohlc_context(idx, rng):
    n = 60
    close = 100.0 + np.cumsum(rng.randn(n) * 0.002)
    open_ = close * (1 + rng.randn(n) * 0.001)
    high = np.maximum(open_, close) + np.abs(rng.randn(n)) * 0.01
    low = np.minimum(open_, close) - np.abs(rng.randn(n)) * 0.01
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})

def make_ohlcv_context(idx, rng):
    n = 60
    close = 100.0 + np.cumsum(np.random.RandomState(idx + SEED).randn(n) * 0.002)
    open_ = close * (1 + np.random.RandomState(idx + SEED).randn(n) * 0.001)
    high = np.maximum(open_, close) + np.abs(np.random.RandomState(idx + SEED).randn(n)) * 0.01
    low = np.minimum(open_, close) - np.abs(np.random.RandomState(idx + SEED).randn(n)) * 0.01
    volume = np.random.RandomState(idx + SEED).uniform(1000, 5000, n)
    amount = volume * close
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": amount})

# ── Load real predictor ──
from engine.kronos_adapter.predictor import KronosPredictor
predictor = KronosPredictor()
predictor_class = type(predictor).__name__
assert predictor_class == "KronosPredictor", f"Expected real KronosPredictor, got {predictor_class}"

# ── Timing ──
run_start = time.time()
model_load_start = time.time()
# Model loads lazily on first predict call
_ = predictor._model  # force load
model_load_duration = time.time() - model_load_start
inference_start = time.time()
predict_calls = 0

all_rows = []
contexts_completed = 0
contexts_failed = 0
contexts_attempted = 0

# Generate all contexts upfront (deterministic)
rng_master = np.random.RandomState(SEED)
contexts = []
for i in range(OHLC_CONTEXTS):
    contexts.append(("OHLC", i, make_ohlc_context(i, rng_master)))
for i in range(OHLCV_CONTEXTS):
    contexts.append(("OHLCV+amount", i, make_ohlcv_context(i, rng_master)))

for schema, ctx_id, df in contexts:
    contexts_attempted += 1
    x_ts = pd.date_range("2026-06-01", periods=60, freq="D")
    y_ts = pd.date_range("2026-08-01", periods=PREDICTION_LENGTH, freq="D")

    try:
        t0 = time.time()
        result = predictor.predict(
            df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            prediction_length=PREDICTION_LENGTH,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            sample_count=SAMPLE_COUNT,
            seed=SEED,
        )
        predict_calls += 1
        inference_duration = time.time() - t0
        contexts_completed += 1

        raw = result.raw_predictions
        projected = result.projected_predictions
        raw_valid = result.raw_validity
        projected_valid = result.projected_validity
        proj_applied = result.projection_applied
        meta = result.projection_metadata

        for h in range(PREDICTION_LENGTH):
            row = {
                "run_id": RUN_ID,
                "schema": schema,
                "context_id": f"{schema}_{ctx_id:04d}",
                "horizon": h + 1,
                "raw_open": float(raw.iloc[h]["open"]),
                "raw_high": float(raw.iloc[h]["high"]),
                "raw_low": float(raw.iloc[h]["low"]),
                "raw_close": float(raw.iloc[h]["close"]),
                "projected_open": float(projected.iloc[h]["open"]),
                "projected_high": float(projected.iloc[h]["high"]),
                "projected_low": float(projected.iloc[h]["low"]),
                "projected_close": float(projected.iloc[h]["close"]),
                "raw_valid": bool(raw_valid.iloc[h]) if hasattr(raw_valid, "iloc") else bool(raw_valid[h]),
                "projected_valid": bool(projected_valid.iloc[h]) if hasattr(projected_valid, "iloc") else bool(projected_valid[h]),
                "projection_applied": proj_applied,
                "high_adjustment": float(projected.iloc[h]["high"] - raw.iloc[h]["high"]),
                "low_adjustment": float(raw.iloc[h]["low"] - projected.iloc[h]["low"]),
                "total_absolute_adjustment": float(abs(projected.iloc[h]["high"] - raw.iloc[h]["high"]) + abs(raw.iloc[h]["low"] - projected.iloc[h]["low"])),
                "relative_adjustment": None,  # computed at summary level
                "predictor_class": predictor_class,
                "model_sha256": CHECKPOINT_SHA,
                "tokenizer_sha256": TOKENIZER_SHA,
                "seed": SEED,
                "temperature": TEMPERATURE,
                "top_p": TOP_P,
                "sample_count": SAMPLE_COUNT,
            }
            # Compute relative adjustment
            origin_close = raw.iloc[0]["close"] if h == 0 else raw.iloc[0]["close"]
            total_abs = abs(projected.iloc[h]["high"] - raw.iloc[h]["high"]) + abs(raw.iloc[h]["low"] - projected.iloc[h]["low"])
            row["relative_adjustment"] = float(total_abs / abs(origin_close)) if origin_close != 0 else None
            all_rows.append(row)
    except Exception as e:
        contexts_failed += 1
        print(f"FAILED context {schema}_{ctx_id:04d}: {e}", file=sys.stderr)

inference_duration_total = time.time() - inference_start
run_end = time.time()
wall_duration = run_end - run_start

# ── Write predictions CSV ──
pred_df = pd.DataFrame(all_rows)
csv_path = OUTPUT_DIR / f"stress_{RUN_ID}_predictions.csv"
pred_df.to_csv(csv_path, index=False)

# ── Compute statistics ──
n_rows = len(pred_df)
raw_valid_count = pred_df["raw_valid"].sum()
raw_invalid_count = n_rows - raw_valid_count
projected_valid_count = pred_df["projected_valid"].sum()
projection_count = pred_df[pred_df["projection_applied"] == True].shape[0]
projection_freq = projection_count / n_rows if n_rows > 0 else None

adjustments = pred_df["total_absolute_adjustment"].dropna()
mean_adj = float(adjustments.mean()) if len(adjustments) > 0 else None
median_adj = float(adjustments.median()) if len(adjustments) > 0 else None
max_adj = float(adjustments.max()) if len(adjustments) > 0 else None
max_rel_adj = float(pred_df["relative_adjustment"].dropna().max()) if pred_df["relative_adjustment"].notna().any() else None

# By horizon
stats_by_horizon = {}
for h in range(1, PREDICTION_LENGTH + 1):
    hdf = pred_df[pred_df["horizon"] == h]
    stats_by_horizon[str(h)] = {
        "count": int(len(hdf)),
        "raw_valid": int(hdf["raw_valid"].sum()),
        "raw_invalid": int((~hdf["raw_valid"]).sum()),
        "raw_validity_rate": float(hdf["raw_valid"].mean()) if len(hdf) > 0 else None,
        "projected_valid": int(hdf["projected_valid"].sum()),
        "projected_validity_rate": float(hdf["projected_valid"].mean()) if len(hdf) > 0 else None,
        "projection_frequency": float(hdf["projection_applied"].mean()) if len(hdf) > 0 else None,
        "mean_adjustment": float(hdf["total_absolute_adjustment"].mean()) if len(hdf) > 0 else None,
        "median_adjustment": float(hdf["total_absolute_adjustment"].median()) if len(hdf) > 0 else None,
        "max_adjustment": float(hdf["total_absolute_adjustment"].max()) if len(hdf) > 0 else None,
    }

# By schema
stats_by_schema = {}
for schema in ["OHLC", "OHLCV+amount"]:
    sdf = pred_df[pred_df["schema"] == schema]
    stats_by_schema[schema] = {
        "count": int(len(sdf)),
        "raw_valid": int(sdf["raw_valid"].sum()),
        "raw_invalid": int((~sdf["raw_valid"]).sum()),
        "raw_validity_rate": float(sdf["raw_valid"].mean()) if len(sdf) > 0 else None,
        "projected_valid": int(sdf["projected_valid"].sum()),
        "projected_validity_rate": float(sdf["projected_valid"].mean()) if len(sdf) > 0 else None,
        "projection_frequency": float(sdf["projection_applied"].mean()) if len(sdf) > 0 else None,
        "mean_adjustment": float(sdf["total_absolute_adjustment"].mean()) if len(sdf) > 0 else None,
        "median_adjustment": float(sdf["total_absolute_adjustment"].median()) if len(sdf) > 0 else None,
        "max_adjustment": float(sdf["total_absolute_adjustment"].max()) if len(sdf) > 0 else None,
    }

# Ten largest adjustments
top10 = pred_df.nlargest(10, "total_absolute_adjustment")[
    ["schema", "context_id", "horizon", "raw_open", "raw_high", "raw_low", "raw_close",
     "projected_high", "projected_low", "high_adjustment", "low_adjustment", "total_absolute_adjustment", "relative_adjustment"]
].to_dict(orient="records")

# Peak RSS
peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB on Linux

# Build JSON summary
summary = {
    "run_id": RUN_ID,
    "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(run_start)),
    "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(run_end)),
    "wall_clock_duration_seconds": round(wall_duration, 3),
    "model_load_duration_seconds": round(model_load_duration, 3),
    "inference_duration_seconds": round(inference_duration_total, 3),
    "peak_rss_kb": peak_rss_kb,
    "predict_call_count": predict_calls,
    "contexts_attempted": contexts_attempted,
    "contexts_completed": contexts_completed,
    "contexts_failed": contexts_failed,
    "rows_produced": n_rows,
    "raw_valid_rows": int(raw_valid_count),
    "raw_invalid_rows": int(raw_invalid_count),
    "raw_validity_rate": float(raw_valid_count / n_rows) if n_rows > 0 else None,
    "projected_valid_rows": int(projected_valid_count),
    "projected_validity_rate": float(projected_valid_count / n_rows) if n_rows > 0 else None,
    "projection_count": int(projection_count),
    "projection_frequency": float(projection_freq) if projection_freq is not None else None,
    "mean_absolute_adjustment": mean_adj,
    "median_absolute_adjustment": median_adj,
    "maximum_absolute_adjustment": max_adj,
    "maximum_relative_adjustment": max_rel_adj,
    "statistics_by_horizon": stats_by_horizon,
    "statistics_by_schema": stats_by_schema,
    "ten_largest_adjustments": top10,
    "checkpoint_sha256": CHECKPOINT_SHA,
    "tokenizer_sha256": TOKENIZER_SHA,
    "seed": SEED,
    "temperature": TEMPERATURE,
    "top_p": TOP_P,
    "sample_count": SAMPLE_COUNT,
    "predictor_class": predictor_class,
    "model_repo": MODEL_REPO,
    "model_revision": MODEL_REVISION,
    "tokenizer_repo": TOKENIZER_REPO,
    "tokenizer_revision": TOKENIZER_REVISION,
    "device": "cpu",
}

json_path = OUTPUT_DIR / f"stress_{RUN_ID}.json"
with open(json_path, "w") as f:
    json.dump(summary, f, indent=2, default=str)

print(f"✓ {RUN_ID}: {n_rows} rows, {contexts_completed}/{contexts_attempted} contexts, {wall_duration:.1f}s")
print(f"  JSON: {json_path}")
print(f"  CSV: {csv_path}")
PYEOF
echo "Stress script written OK"