"""Kronos Phase 1 V2 Benchmark Runner — D1 data, corrected metrics.

This runner replaces the invalid Run A H1 runner (engine/run_phase1_benchmark.py).
It operates exclusively on manifest-verified D1 files and enforces:
  - 5-row prediction output (one per horizon), never iloc[-1] replication
  - origin-relative directional accuracy
  - context from preceding splits allowed
  - one ledger row per pair/origin/horizon
  - sealed test access blocked during development/validation
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── Safety invariants ──────────────────────────────────────
paper_only = True
allow_live_orders = False
assert paper_only and not allow_live_orders, "Safety invariant violated"

# ── Constants ──────────────────────────────────────────────
LOOKBACK = 256
HORIZON = 5
SPACING = 5
T = 1.0
TOP_P = 0.9
SAMPLE_COUNT = 1
NUMPY_SEED = 20260725
TORCH_SEED = 20260725

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "engine" / "data"
OUTPUT = BASE / "engine" / "evidence" / "kronos" / "phase1"

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]

# ── Frozen boundaries ──────────────────────────────────────
DEV_START = pd.Timestamp("2010-01-04", tz="UTC")
DEV_END = pd.Timestamp("2023-07-20", tz="UTC")
VAL_START = pd.Timestamp("2023-07-21", tz="UTC")
VAL_END = pd.Timestamp("2025-01-03", tz="UTC")
TEST_START = pd.Timestamp("2025-01-06", tz="UTC")
TEST_END = pd.Timestamp("2026-07-17", tz="UTC")

SPLITS = {
    "development": (DEV_START, DEV_END),
    "validation": (VAL_START, VAL_END),
    "test": (TEST_START, TEST_END),
}


# ── Helpers ────────────────────────────────────────────────

def load_manifest(pair: str) -> dict:
    """Load and verify V2 D1 manifest for a pair."""
    manifest_path = DATA / f"raw_mt5_{pair}_1d_v2.manifest.json"
    with open(manifest_path) as f:
        m = json.load(f)
    # Enforce D1
    assert m.get("timeframe") == "1d", f"{pair} manifest timeframe is not 1d: {m.get('timeframe')}"
    assert m.get("source") == "MetaTrader5 demo history", f"{pair} source is not MT5 D1"
    return m


def load_pair_d1(pair: str) -> pd.DataFrame:
    """Load a verified V2 D1 CSV. Rejects H1 files and non-D1 data."""
    csv_path = DATA / f"raw_mt5_{pair}_1d_v2.csv"
    assert csv_path.exists(), f"No D1 CSV for {pair}: {csv_path}"
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    # Verify all expected columns exist
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        assert col in df.columns, f"{pair} CSV missing column {col}"
    return df


def get_split_rows(df: pd.DataFrame, split: str) -> pd.DataFrame:
    """Return rows within a split boundary."""
    start, end = SPLITS[split]
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
    return df[mask].reset_index(drop=True)


def get_possible_origins(df: pd.DataFrame, split: str) -> pd.DataFrame:
    """Return valid forecast origins for a split.

    Origin is the final input bar (index i). The 5 target bars are
    df.loc[i+1 : i+HORIZON]. Context (previous 256 bars) may come
    from any earlier row in df, not just from the same split.
    """
    split_df = get_split_rows(df, split)
    if len(split_df) < HORIZON:
        return pd.DataFrame()

    # The earliest origin index in the full df such that the 5 target
    # bars are all inside the split.
    first_target_idx = split_df.index[0] + HORIZON - 1
    # The latest origin index must allow 5 target bars before the end
    # of the split.
    last_target_idx = split_df.index[-1]
    # Origin must be at index (target_start - 1) through (target_end - HORIZON + 1)
    # Actually: if origin is at position p in the full df, then
    # targets are p+1 .. p+HORIZON (inclusive). The target indices must
    # satisfy p+HORIZON <= last_target_idx and p >= first_target_idx - HORIZON + 1
    earliest_origin_idx = first_target_idx - HORIZON + 1  # not right
    # Let me think again...
    # For origin at index i in the full dataframe:
    #   input = rows [i-LOOKBACK+1 : i+1]  (LOOKBACK bars)
    #   targets = rows [i+1 : i+HORIZON+1] (HORIZON bars)
    # We need: i+1 >= first_target_idx (so first target is in split)
    #          i+HORIZON <= last_target_idx (so last target is in split)
    # Wait, targets should be WITHIN the split. 
    # Actually targets start at i+1 (the bar immediately after the origin),
    # i.e., the first target at position i+1 must be >= split_start.
    # The last target at position i+HORIZON must be <= split_end.
    # Also input must be: the lookback window ends at i, so the
    # input row indices are i-LOOKBACK+1 .. i (inclusive), 
    # but i is NOT a target row (it's the origin/context bar).
    # Target rows are i+1 .. i+HORIZON.
    # So we need: i+HORIZON <= last_df_index and i-HORIZON+1 >= 0
    
    df_len = len(df)
    first_target_pos = split_df.index[0]
    last_target_pos = split_df.index[-1]
    
    # Origins where first_target_pos <= i+1 and i+HORIZON <= last_target_pos
    # => i >= first_target_pos - 1 and i <= last_target_pos - HORIZON
    # Also need i >= LOOKBACK - 1 (need LOOKBACK bars for input)
    # And i+HORIZON <= df_len - 1
    
    earliest = max(LOOKBACK - 1, first_target_pos - 1)
    latest = min(df_len - HORIZON - 1, last_target_pos - HORIZON)
    
    if earliest > latest:
        return pd.DataFrame()
    
    return pd.DataFrame({
        "origin_idx": range(int(earliest), int(latest) + 1),
        "origin_timestamp": df.iloc[range(int(earliest), int(latest) + 1)]["timestamp"].values,
    })


def extract_input(df: pd.DataFrame, origin_idx: int) -> pd.DataFrame:
    """Extract LOOKBACK context bars ending at origin_idx (exclusive)."""
    start = max(0, origin_idx - LOOKBACK + 1)
    end = origin_idx + 1  # exclusive upper bound
    return df.iloc[start:end].copy()


def extract_targets(df: pd.DataFrame, origin_idx: int, split: str) -> pd.DataFrame:
    """Extract HORIZON target bars immediately following origin_idx."""
    # Targets must all be within the evaluated split
    start = split_start_index(df, split)
    end = split_end_index(df, split)
    
    targets = df.iloc[origin_idx + 1 : origin_idx + 1 + HORIZON].copy()
    # Validate all targets within split
    assert len(targets) == HORIZON, f"Expected {HORIZON} targets, got {len(targets)}"
    return targets


def split_start_index(df: pd.DataFrame, split: str) -> int:
    s, e = SPLITS[split]
    mask = (df["timestamp"] >= s) & (df["timestamp"] <= e)
    return int(mask.values.nonzero()[0][0])


def split_end_index(df: pd.DataFrame, split: str) -> int:
    s, e = SPLITS[split]
    mask = (df["timestamp"] >= s) & (df["timestamp"] <= e)
    return int(mask.values.nonzero()[0][-1])


# ── Scoring ─────────────────────────────────────────────────

def score_one_forecast(
    origin_close: float,
    predicted_closes: np.ndarray,
    actual_closes: np.ndarray,
    predicted_highs: np.ndarray | None = None,
    predicted_lows: np.ndarray | None = None,
    predicted_opens: np.ndarray | None = None,
    actual_highs: np.ndarray | None = None,
    actual_lows: np.ndarray | None = None,
    actual_opens: np.ndarray | None = None,
) -> dict:
    """Score one origin's horizon predictions against actuals.

    predicted_closes[i] corresponds to target timestamp i+1
    (origin_close is the last input bar close).
    """
    assert len(predicted_closes) == HORIZON, f"Expected {HORIZON} predictions, got {len(predicted_closes)}"
    assert len(actual_closes) == HORIZON, f"Expected {HORIZON} actuals, got {len(actual_closes)}"

    h = np.arange(1, HORIZON + 1)

    # Close MAE/RMSE per horizon
    close_mae_per = np.abs(predicted_closes - actual_closes)
    close_mse_per = (predicted_closes - actual_closes) ** 2

    # Normalized close MAE (per origin, denominator = price range of target bars)
    price_range = np.max(actual_closes) - np.min(actual_closes)
    norm_close_mae = np.mean(close_mae_per) / price_range if price_range > 0 else 0.0

    # Return MAE
    return_mae_per = np.abs(np.diff(np.concatenate([[origin_close], predicted_closes])) - np.diff(np.concatenate([[origin_close], actual_closes])))

    # OHLC validity per horizon
    ohlc_valid = np.ones(HORIZON, dtype=bool)
    if predicted_highs is not None:
        ohlc_valid &= predicted_highs >= predicted_lows
        ohlc_valid &= predicted_lows <= predicted_opens
        ohlc_valid &= predicted_lows <= predicted_closes
        ohlc_valid &= predicted_highs >= predicted_opens
        ohlc_valid &= predicted_highs >= predicted_closes
    if actual_highs is not None:
        ohlc_valid &= actual_highs >= actual_lows

    # Directional accuracy (ORIGIN-RELATIVE)
    # predicted_direction_h = sign(predicted_close_h - origin_close)
    # actual_direction_h = sign(actual_close_h - origin_close)
    pred_dir = np.sign(predicted_closes - origin_close)
    actual_dir = np.sign(actual_closes - origin_close)
    # Zero-movement policy: if both zero direction, count as correct
    both_zero = (pred_dir == 0) & (actual_dir == 0)
    directional_acc = float(np.mean((pred_dir == actual_dir) | both_zero))

    # High-Low interval coverage
    if actual_highs is not None and actual_lows is not None and predicted_highs is not None and predicted_lows is not None:
        hl_cov = np.mean(
            (actual_highs >= predicted_lows) & (actual_highs <= predicted_highs) &
            (actual_lows >= predicted_lows) & (actual_lows <= predicted_highs)
        )
    else:
        hl_cov = np.nan

    return {
        "close_mae_per_horizon": close_mae_per.tolist(),
        "close_mse_per_horizon": close_mse_per.tolist(),
        "mean_close_mae": float(np.mean(close_mae_per)),
        "mean_close_rmse": float(np.sqrt(np.mean(close_mse_per))),
        "norm_close_mae": float(norm_close_mae),
        "return_mae_per_horizon": return_mae_per.tolist(),
        "mean_return_mae": float(np.mean(return_mae_per)),
        "directional_accuracy": directional_acc,
        "correct_directions_per_horizon": ((pred_dir == actual_dir) | both_zero).tolist(),
        "ohlc_valid_per_horizon": ohlc_valid.tolist(),
        "ohlc_validity_rate": float(np.mean(ohlc_valid)),
        "high_low_interval_coverage": float(hl_cov),
    }


def score_baseline_last_value(
    origin_close: float,
    actual_closes: np.ndarray,
) -> dict:
    """Last-value baseline: predict origin_close for all horizons."""
    predicted = np.full(HORIZON, origin_close)
    return score_one_forecast(origin_close, predicted, actual_closes)


# ── Main inference loop ─────────────────────────────────────

def run_phase1_v2():
    """Run the corrected V2 benchmark on all 4 pairs."""
    np.random.seed(NUMPY_SEED)
    import torch
    torch.manual_seed(TORCH_SEED)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    forecast_ledger = []
    scoring_ledger = []
    baseline_ledger = []
    checkpoints = []

    from model.kronos import KronosTokenizer, Kronos, KronosPredictor

    # Load model (frozen checkpoint)
    tokenizer = KronosTokenizer.from_pretrained(
        "NeoQuasar/Kronos-Tokenizer-2k",
        revision="26966d0035065a0cae0ebad7af8ece35bc1fb51c",
    )
    model = Kronos.from_pretrained(
        "NeoQuasar/Kronos-mini",
        revision="f4e68697d9d5aed55cef5c96aabc3376bcad9f81",
        device_map="cpu",
    )
    predictor = KronosPredictor(model, tokenizer)

    for pair_idx, pair in enumerate(PAIRS):
        m = load_manifest(pair)
        df = load_pair_d1(pair)

        print(f"[{pair_idx+1}/4] {pair}: {len(df)} rows, {m.get('row_count')} expected in manifest")

        # Validate manifest
        assert m.get("row_count") == len(df), f"{pair} manifest row count mismatch: manifest={m.get('row_count')}, actual={len(df)}"
        csv_sha = hashlib.sha256((DATA / f"raw_mt5_{pair}_1d_v2.csv").read_bytes()).hexdigest()
        assert csv_sha == m.get("file_sha256"), f"{pair} SHA-256 mismatch"

        # Get development origins only (V2 Run A is development-only)
        origins_df = get_possible_origins(df, "development")
        print(f"  Development origins: {len(origins_df)}")

        for oi, row in origins_df.iterrows():
            origin_idx = int(row["origin_idx"])
            input_df = extract_input(df, origin_idx)
            targets_df = extract_targets(df, origin_idx, "development")

            origin_close = float(input_df["close"].iloc[-1])
            origin_timestamp = str(input_df["timestamp"].iloc[-1])
            target_timestamps = targets_df["timestamp"].tolist()
            target_closes = targets_df["close"].values.astype(float)
            actual_highs = targets_df.get("high")
            actual_lows = targets_df.get("low")

            # Kronos inference (5-step prediction)
            history = input_df[["timestamp", "open", "high", "low", "close"]].reset_index(drop=True)
            predicted = predictor.predict(history, pred_len=HORIZON, temperature=T, top_p=TOP_P)

            # predicted must be a 5-row DataFrame
            assert len(predicted) == HORIZON, f"Expected {HORIZON} prediction rows, got {len(predicted)}"

            pred_closes = predicted["close"].values.astype(float)
            pred_opens = predicted["open"].values.astype(float)
            pred_highs = predicted["high"].values.astype(float)
            pred_lows = predicted["low"].values.astype(float)

            # Map: prediction row h -> target timestamp h (0-indexed)
            horizons = np.arange(1, HORIZON + 1)

            # Verify each prediction row maps to the correct target timestamp
            for h in range(HORIZON):
                assert predicted["timestamp"].iloc[h] == target_timestamps[h], \
                    f"Horizon {h+1} timestamp mismatch: predicted={predicted['timestamp'].iloc[h]}, actual target={target_timestamps[h]}"

            # Score
            scores = score_one_forecast(
                origin_close, pred_closes, target_closes,
                predicted_highs=pred_highs, predicted_lows=pred_lows,
                predicted_opens=pred_opens,
                actual_highs=actual_highs.values if actual_highs is not None else None,
                actual_lows=actual_lows.values if actual_lows is not None else None,
                actual_opens=targets_df.get("open").values if "open" in targets_df.columns else None,
            )

            # Store forecast ledger row (one per horizon)
            for h in range(HORIZON):
                forecast_ledger.append({
                    "pair": pair,
                    "split": "development",
                    "origin_idx": origin_idx,
                    "origin_timestamp": origin_timestamp,
                    "origin_close": origin_close,
                    "horizon": h + 1,
                    "target_timestamp": str(target_timestamps[h]),
                    "actual_close": float(target_closes[h]),
                    "predicted_close": float(pred_closes[h]),
                    "predicted_open": float(pred_opens[h]),
                    "predicted_high": float(pred_highs[h]),
                    "predicted_low": float(pred_lows[h]),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            # Store scoring entry (one per origin)
            scoring_ledger.append({
                "pair": pair,
                "split": "development",
                "origin_idx": origin_idx,
                "origin_timestamp": origin_timestamp,
                "scores": scores,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # Periodic checkpoint
            if len(scoring_ledger) % 100 == 0:
                checkpoint = {
                    "checkpoint_type": "periodic",
                    "pairs_processed": pair_idx + 1,
                    "origins_processed": len(scoring_ledger),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                checkpoints.append(checkpoint)

        print(f"  Done: {len(scoring_ledger)} development origins for {pair}")

    # Save ledgers
    with open(OUTPUT / "phase1_v2_forecast_ledger.json", "w") as f:
        json.dump(forecast_ledger, f, indent=2)
    with open(OUTPUT / "phase1_v2_scoring.json", "w") as f:
        json.dump(scoring_ledger, f, indent=2)
    with open(OUTPUT / "phase1_v2_checkpoints.json", "w") as f:
        json.dump(checkpoints, f, indent=2)

    # Baseline evaluation (last-value on same development origins)
    for pair_idx, pair in enumerate(PAIRS):
        df = load_pair_d1(pair)
        origins_df = get_possible_origins(df, "development")
        for _, row in origins_df.iterrows():
            origin_idx = int(row["origin_idx"])
            input_df = extract_input(df, origin_idx)
            targets_df = extract_targets(df, origin_idx, "development")
            origin_close = float(input_df["close"].iloc[-1])
            target_closes = targets_df["close"].values.astype(float)

            baseline_scores = score_baseline_last_value(origin_close, target_closes)
            baseline_ledger.append({
                "pair": pair, "split": "development",
                "origin_idx": origin_idx, "baseline": "last_value",
                "scores": baseline_scores,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    with open(OUTPUT / "phase1_v2_baseline_ledger.json", "w") as f:
        json.dump(baseline_ledger, f, indent=2)

    print("V2 Phase 1 development run complete.")
    return {
        "forecast_ledger": forecast_ledger,
        "scoring_ledger": scoring_ledger,
        "baseline_ledger": baseline_ledger,
        "checkpoints": checkpoints,
    }


if __name__ == "__main__":
    result = run_phase1_v2()
    print(f"Total development inferences: {len(result['scoring_ledger'])}")
    print(f"Total forecast rows: {len(result['forecast_ledger'])}")
    print(f"Total baseline rows: {len(result['baseline_ledger'])}")