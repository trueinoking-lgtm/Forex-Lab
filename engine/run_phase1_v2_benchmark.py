"""Kronos Phase 1 V2 Benchmark Runner — D1 data, corrected metrics.

KRONOS PHASE 1 V2 — D1 ONLY
RUN A H1 EVALUATION INVALIDATED

Production runner with explicit execution stages and origin freeze.
Modes: --stage development | validation | seeded-test | count-only

Staking order:
  A: development execution
  B: development evidence replay and freeze
  C: validation execution
  D: validation evidence replay and decision freeze
  E: manual sealed-test authorisation
  F: sealed-test execution exactly once

Do not execute sealed test automatically after validation.
Do not alter model settings, baselines, metrics, folds or advancement rules between stages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── Safety invariants ──────────────────────────────────
paper_only = True
allow_live_orders = False
assert paper_only and not allow_live_orders, "Safety invariant violated"

# ── Constants ──────────────────────────────────────────
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
ORIGIN_MANIFEST = BASE / "engine" / "docs" / "manifests" / "kronos_phase1_v2_origin_manifest.json"

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]

# ── Frozen boundaries ──────────────────────────────────
DEV_START = pd.Timestamp("2010-01-04", tz="UTC")
DEV_END = pd.Timestamp("2023-07-20", tz="UTC")
VAL_START = pd.Timestamp("2023-07-21", tz="UTC")
VAL_END = pd.Timestamp("2025-01-03", tz="UTC")
TEST_START = pd.Timestamp("2025-01-06", tz="UTC")
TEST_END = pd.Timestamp("2026-07-17", tz="UTC")

# ── Frozen stage order ─────────────────────────────────
STAGES = ["development", "validation", "sealed-test"]

# ── Stage data-visibility boundaries ────────────────
# Each stage may only ACCESS rows through its end boundary.
# Validation may use development rows as context (they are <= VAL_END).
# Sealed-test may use development+validation rows as context (they are <= TEST_END).
STAGE_VISIBILITY_END = {
    "development": DEV_END,
    "validation": VAL_END,
    "sealed-test": TEST_END,
}

STAGE_TARGET_SPLIT = {
    "development": "development",
    "validation": "validation",
    "sealed-test": "test",
}

# Internal split key used in SPLITS — "test" for sealed-test
SPLIT_KEY = {
    "development": "development",
    "validation": "validation",
    "sealed-test": "test",
}

SPLITS = {
    "development": (DEV_START, DEV_END),
    "validation": (VAL_START, VAL_END),
    "test": (TEST_START, TEST_END),
}


def parse_args():
    parser = argparse.ArgumentParser(description="Kronos Phase 1 V2 benchmark runner")
    parser.add_argument(
        "--stage",
        choices=STAGES + ["count-only"],
        required=True,
        help="Execution stage: development, validation, sealed-test, or count-only",
    )
    parser.add_argument(
        "--unseal",
        action="store_true",
        help="Required for sealed-test stage. Explicit authorisation flag.",
    )
    parser.add_argument(
        "--expected-config-hash",
        type=str,
        default=None,
        help="SHA-256 of the frozen configuration file for sealed-test authorisation",
    )
    parser.add_argument(
        "--expected-dataset-manifest-hash",
        type=str,
        default=None,
        help="SHA-256 of the frozen dataset manifest for sealed-test authorisation",
    )
    parser.add_argument(
        "--expected-fold-manifest-hash",
        type=str,
        default=None,
        help="SHA-256 of the frozen fold manifest for sealed-test authorisation",
    )
    parser.add_argument(
        "--expected-metric-spec-hash",
        type=str,
        default=None,
        help="SHA-256 of the frozen metric spec for sealed-test authorisation",
    )
    parser.add_argument(
        "--expected-origin-manifest-hash",
        type=str,
        default=None,
        help="SHA-256 of the frozen origin manifest for sealed-test authorisation",
    )
    parser.add_argument(
        "--expected-code-commit",
        type=str,
        default=None,
        help="Git commit hash for frozen code state for sealed-test authorisation",
    )
    parser.add_argument(
        "--origin-manifest",
        type=str,
        default=None,
        help="Path to origin manifest JSON (for validation against runtime origins)",
    )
    return parser.parse_args()


# ── Helpers ──────────────────────────────────────────────

def load_manifest(pair: str) -> dict:
    """Load and verify V2 D1 manifest for a pair."""
    manifest_path = DATA / f"raw_mt5_{pair}_1d_v2.manifest.json"
    with open(manifest_path) as f:
        m = json.load(f)
    assert m.get("timeframe") == "1d", f"{pair} manifest timeframe is not 1d: {m.get('timeframe')}"
    assert m.get("source") == "MetaTrader5 demo history", f"{pair} source is not MT5 D1"
    return m


def load_pair_d1(pair: str, stage: str = "development") -> pd.DataFrame:
    """Load a verified V2 D1 CSV with data-visibility boundary enforcement.

    In development mode, only rows through DEV_END are loaded.
    In validation mode, only rows through VAL_END are loaded.
    In sealed-test mode, only rows through TEST_END are loaded.

    This is a HARD boundary — rows past the stage's visibility end
    are not accessible, not even for context.
    """
    csv_path = DATA / f"raw_mt5_{pair}_1d_v2.csv"
    assert csv_path.exists(), f"No D1 CSV for {pair}: {csv_path}"
    df = pd.read_csv(csv_path)
    # Detect separator
    with open(csv_path, "r") as f:
        first_line = f.readline()
    sep = "\t" if "\t" in first_line else ","
    df = pd.read_csv(csv_path, sep=sep)
    # Normalize column names
    col_map = {}
    for c in df.columns:
        if c in ("timestamp", "<DATE>"):
            col_map[c] = "timestamp"
        elif c in ("open", "Open"):
            col_map[c] = "open"
        elif c in ("high", "High"):
            col_map[c] = "high"
        elif c in ("low", "Low"):
            col_map[c] = "low"
        elif c in ("close", "Close"):
            col_map[c] = "close"
        elif c in ("volume", "Volume", "tick_volume"):
            col_map[c] = "volume"
    df = df.rename(columns=col_map)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Apply data-visibility boundary (development mode)
    vis_end = STAGE_VISIBILITY_END[stage]
    df = df[df["timestamp"] <= vis_end].reset_index(drop=True)

    return df


def get_split_rows(df: pd.DataFrame, split: str) -> pd.DataFrame:
    """Return rows within a split boundary."""
    start, end = SPLITS[split]
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
    return df[mask].reset_index(drop=True)


def get_possible_origins(df: pd.DataFrame, split: str) -> pd.DataFrame:
    """Return valid forecast origins for a split with SPACING=5 downsampling.

    Returns origins as full-dataframe index positions (not split-relative).
    An origin at dataframe index i produces:
    - input: rows [i-LOOKBACK+1 .. i] (256 bars)
    - targets: rows [i+1 .. i+HORIZON] (5 bars, all must be inside split)

    Context bars before the origin may come from earlier splits.
    """
    split_df = get_split_rows(df, split)
    if len(split_df) < HORIZON:
        return pd.DataFrame()

    # split_df has reset_index(drop=True) so .index starts at 0.
    # But we need the ORIGINAL full-df positions of the split rows.
    # Build a boolean mask on the full df and use .values.nonzero() to get
    # real positions.
    start, end = SPLITS[split]
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
    positions = mask.values.nonzero()[0]

    first_target_pos = int(positions[0])
    last_target_pos = int(positions[-1])
    df_len = len(df)

    # origin i: targets are i+1 .. i+HORIZON
    # constraint 1: i+1 >= first_target_pos  =>  i >= first_target_pos - 1
    # constraint 2: i+HORIZON <= last_target_pos  =>  i <= last_target_pos - HORIZON
    # constraint 3: i >= LOOKBACK - 1  (need LOOKBACK bars for input)
    # constraint 4: i+HORIZON <= df_len - 1  (need 5 bars to exist in df)

    earliest = max(LOOKBACK - 1, first_target_pos - 1)
    latest = min(df_len - HORIZON - 1, last_target_pos - HORIZON)

    if earliest > latest:
        return pd.DataFrame()

    # Apply SPACING downsampling: every 5th origin
    origin_indices = range(int(earliest), int(latest) + 1, SPACING)
    origin_indices = [i for i in origin_indices if i >= earliest and i <= latest]

    return pd.DataFrame({
        "origin_idx": origin_indices,
        "origin_timestamp": df.iloc[origin_indices]["timestamp"].values,
    })


def extract_input(df: pd.DataFrame, origin_idx: int) -> pd.DataFrame:
    """Extract LOOKBACK context bars ending at origin_idx."""
    start = max(0, origin_idx - LOOKBACK + 1)
    end = origin_idx + 1
    return df.iloc[start:end].copy()


def extract_targets(df: pd.DataFrame, origin_idx: int, split: str) -> pd.DataFrame:
    """Extract HORIZON target bars immediately following origin_idx."""
    targets = df.iloc[origin_idx + 1 : origin_idx + 1 + HORIZON].copy()
    assert len(targets) == HORIZON, f"Expected {HORIZON} targets, got {len(targets)}"
    return targets


# ── Origin manifest ─────────────────────────────────────

def generate_origin_manifest() -> dict:
    """Generate the complete origin manifest for all pairs and splits."""
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback": LOOKBACK,
        "horizon": HORIZON,
        "spacing": SPACING,
        "pairs": {},
        "totals": {"development": 0, "validation": 0, "test": 0, "grand_total": 0},
    }

    for split in ["development", "validation", "test"]:
        split_start, split_end = SPLITS[split]
        # Map internal split key to stage name for STAGE_VISIBILITY lookup
        stage_name = "sealed-test" if split == "test" else split
        visibility_end = STAGE_VISIBILITY_END[stage_name]
        
        for pair in PAIRS:
            m = load_manifest(pair)
            # Load FULL D1 file — all rows accessible for origin calculation
            df = load_pair_d1_full(pair)
            origins_df = get_possible_origins(df, split)
            
            pair_origins_count = len(origins_df)
            if pair not in manifest["pairs"]:
                manifest["pairs"][pair] = {}
            manifest["pairs"][pair][split] = pair_origins_count
            # Store CSV SHA-256 for guard verification
            csv_csv_path = DATA / f"raw_mt5_{pair}_1d_v2.csv"
            csv_sha = hashlib.sha256(csv_csv_path.read_bytes()).hexdigest()
            manifest["pairs"][pair]["_csv_sha256"] = csv_sha
            
            manifest["totals"][split] += pair_origins_count

    manifest["totals"]["grand_total"] = sum(
        manifest["totals"][s] for s in ["development", "validation", "test"]
    )
    return manifest


def load_pair_d1_full(pair: str) -> pd.DataFrame:
    """Load the complete un-truncated V2 D1 CSV for origin calculation.

    Unlike load_pair_d1() (which enforces data-visibility boundaries),
    this loads the full file to enumerate all possible origins across
    all splits. The data-visibility boundary is enforced at execution time,
    not at origin enumeration time.
    """
    csv_path = DATA / f"raw_mt5_{pair}_1d_v2.csv"
    assert csv_path.exists(), f"No D1 CSV for {pair}: {csv_path}"
    with open(csv_path, "r") as f:
        first_line = f.readline()
    sep = "\t" if "\t" in first_line else ","
    df = pd.read_csv(csv_path, sep=sep)
    col_map = {}
    for c in df.columns:
        if c in ("timestamp", "<DATE>"):
            col_map[c] = "timestamp"
        elif c in ("open", "Open"):
            col_map[c] = "open"
        elif c in ("high", "High"):
            col_map[c] = "high"
        elif c in ("low", "Low"):
            col_map[c] = "low"
        elif c in ("close", "Close"):
            col_map[c] = "close"
        elif c in ("volume", "Volume", "tick_volume"):
            col_map[c] = "volume"
    df = df.rename(columns=col_map)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _fold_config_hash() -> str:
    """Hash of the frozen fold configuration."""
    fold_path = BASE / "engine" / "docs" / "kronos_phase1_v2_fold_manifest.json"
    with open(fold_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def compute_source_csv_hashes() -> dict:
    """Return {pair: SHA-256} for each V2 D1 CSV."""
    return {pair: hashlib.sha256(
        (DATA / f"raw_mt5_{pair}_1d_v2.csv").read_bytes()
    ).hexdigest() for pair in PAIRS}


def get_tracked_code_commit() -> str:
    """Return the latest tracked commit hash of the repository."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True,
        cwd=str(BASE),
    )
    return result.stdout.strip()


def _manifest_sha256(manifest: dict) -> str:
    """SHA-256 of the canonical JSON representation of a manifest."""
    canonical = json.dumps(manifest, sort_keys=True, indent=2,
                           separators=(",", ": "))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_tracked_manifest() -> tuple:
    """Load the tracked (committed) origin manifest.

    Returns (manifest_dict, manifest_sha256).
    Raises AssertionError if the manifest file is missing or the
    SHA-256 does not match the committed content.
    """
    assert ORIGIN_MANIFEST.exists(), (
        f"Tracked origin manifest missing: {ORIGIN_MANIFEST}"
    )
    content = ORIGIN_MANIFEST.read_text()
    manifest = json.loads(content)
    actual_sha = hashlib.sha256(content.encode()).hexdigest()
    return manifest, actual_sha


def verify_all_guards(stage: str, expected_config_hash: str | None,
                      expected_code_commit: str | None,
                      expected_manifest_sha: str | None,
                      expected_dataset_manifest_sha: str | None,
                      expected_fold_manifest_sha: str | None,
                      expected_metric_spec_sha: str | None,
                      expected_origin_manifest_sha: str | None) -> None:
    """Verify hashes and identity before any inference stage.

    Raises AssertionError (which causes abort) if any guard fails.
    Checks:
    - source CSV SHA-256 vs manifest-stored values
    - origin manifest SHA-256
    - config file SHA-256
    - dataset manifest SHA-256
    - fold manifest SHA-256
    - metric spec SHA-256
    - code commit hash
    """
    # Verify source CSV hashes against manifest
    csv_hashes = compute_source_csv_hashes()
    tracked_manifest, manifest_sha = load_tracked_manifest()

    # Check origin manifest integrity
    if expected_origin_manifest_sha is not None:
        assert manifest_sha == expected_origin_manifest_sha, (
            f"Origin manifest SHA mismatch: expected {expected_origin_manifest_sha}, "
            f"got {manifest_sha}"
        )

    # Check each CSV against manifest-stored hash
    for pair in PAIRS:
        actual_csv_sha = csv_hashes[pair]
        stored_sha = str(tracked_manifest.get("pairs", {}).get(pair, {}).get(
            "_csv_sha256", ""
        ))
        assert actual_csv_sha == stored_sha, (
            f"{pair} CSV hash does not match tracked manifest: "
            f"actual={actual_csv_sha[:16]}... stored={stored_sha[:16]}..."
        )

    # Verify config file hash
    if expected_config_hash is not None:
        config_path = BASE / "engine" / "docs" / "kronos_phase1_v2_config.json"
        actual_config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
        assert actual_config_hash == expected_config_hash, (
            f"Config hash mismatch: expected {expected_config_hash}, "
            f"got {actual_config_hash}"
        )

    # Verify dataset manifest hash
    if expected_dataset_manifest_sha is not None:
        ds_path = BASE / "engine" / "docs" / "kronos_phase1_v2_dataset_manifest.json"
        actual_ds_hash = hashlib.sha256(ds_path.read_bytes()).hexdigest()
        assert actual_ds_hash == expected_dataset_manifest_sha, (
            f"Dataset manifest hash mismatch: expected {expected_dataset_manifest_sha}, "
            f"got {actual_ds_hash}"
        )

    # Verify fold manifest hash
    if expected_fold_manifest_sha is not None:
        fold_path = BASE / "engine" / "docs" / "kronos_phase1_v2_fold_manifest.json"
        actual_fold_hash = hashlib.sha256(fold_path.read_bytes()).hexdigest()
        assert actual_fold_hash == expected_fold_manifest_sha, (
            f"Fold manifest hash mismatch: expected {expected_fold_manifest_sha}, "
            f"got {actual_fold_hash}"
        )

    # Verify metric spec hash
    if expected_metric_spec_sha is not None:
        ms_path = BASE / "engine" / "docs" / "kronos_phase1_v2_metric_spec.json"
        actual_ms_hash = hashlib.sha256(ms_path.read_bytes()).hexdigest()
        assert actual_ms_hash == expected_metric_spec_sha, (
            f"Metric spec hash mismatch: expected {expected_metric_spec_sha}, "
            f"got {actual_ms_hash}"
        )

    # Verify code commit if provided
    if expected_code_commit is not None:
        actual_commit = get_tracked_code_commit()
        assert actual_commit == expected_code_commit, (
            f"Code commit mismatch: expected {expected_code_commit}, "
            f"got {actual_commit}"
        )


def save_origin_manifest(manifest: dict) -> str:
    """Save the origin manifest and return its SHA-256."""
    ORIGIN_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest, indent=2)
    with open(ORIGIN_MANIFEST, "w") as f:
        f.write(content)
    manifest_sha = hashlib.sha256(content.encode()).hexdigest()
    return manifest_sha


# ── Scoring ─────────────────────────────────────────────

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
    assert len(predicted_closes) == HORIZON
    assert len(actual_closes) == HORIZON
    h = np.arange(1, HORIZON + 1)
    close_mae_per = np.abs(predicted_closes - actual_closes)
    close_mse_per = (predicted_closes - actual_closes) ** 2
    price_range = np.max(actual_closes) - np.min(actual_closes)
    norm_close_mae = np.mean(close_mae_per) / price_range if price_range > 0 else 0.0
    return_mae_per = np.abs(
        np.diff(np.concatenate([[origin_close], predicted_closes]))
        - np.diff(np.concatenate([[origin_close], actual_closes]))
    )
    ohlc_valid = np.ones(HORIZON, dtype=bool)
    if predicted_highs is not None:
        ohlc_valid &= predicted_highs >= predicted_lows
        ohlc_valid &= predicted_lows <= predicted_opens
        ohlc_valid &= predicted_lows <= predicted_closes
        ohlc_valid &= predicted_highs >= predicted_opens
        ohlc_valid &= predicted_highs >= predicted_closes
    if actual_highs is not None:
        ohlc_valid &= actual_highs >= actual_lows
    pred_dir = np.sign(predicted_closes - origin_close)
    actual_dir = np.sign(actual_closes - origin_close)
    both_zero = (pred_dir == 0) & (actual_dir == 0)
    directional_acc = float(np.mean((pred_dir == actual_dir) | both_zero))
    if actual_highs is not None and actual_lows is not None and predicted_highs is not None and predicted_lows is not None:
        hl_cov = np.mean(
            (actual_highs >= predicted_lows) & (actual_highs <= predicted_highs)
            & (actual_lows >= predicted_lows) & (actual_lows <= predicted_highs)
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


def run_count_only():
    """Count-only mode: generate origin manifest and print counts without inference."""
    manifest = generate_origin_manifest()
    manifest_sha = save_origin_manifest(manifest)

    print("COUNT-ONLY MODE — Origin Manifest")
    print("=" * 50)
    for pair in PAIRS:
        counts = manifest["pairs"][pair].get("_counts", {})
        print(f"{pair}: dev={counts.get('development', 0)} val={counts.get('validation', 0)} test={counts.get('test', 0)}")
    print()
    print(f"DEVELOPMENT TOTAL:  {manifest['totals']['development']}")
    print(f"VALIDATION TOTAL:   {manifest['totals']['validation']}")
    print(f"SEALED TEST TOTAL:  {manifest['totals']['test']}")
    print(f"GRAND TOTAL:        {manifest['totals']['grand_total']}")
    print()
    print(f"Origin manifest SHA-256: {manifest_sha}")
    print(f"Origin manifest path:    {ORIGIN_MANIFEST}")

    # Verify expected counts
    assert manifest["totals"]["development"] == 2608, (
        f"Expected 2608 dev origins, got {manifest['totals']['development']}"
    )
    assert manifest["totals"]["validation"] == 302, (
        f"Expected 302 val origins, got {manifest['totals']['validation']}"
    )
    assert manifest["totals"]["test"] == 316, (
        f"Expected 316 test origins, got {manifest['totals']['test']}"
    )
    assert manifest["totals"]["grand_total"] == 3226, (
        f"Expected 3226 total origins, got {manifest['totals']['grand_total']}"
    )
    print("All expected counts verified.")

    # Return manifest for further use
    return manifest, manifest_sha


def run_stage(stage: str, unseal: bool = False,
              expected_config_hash: str | None = None,
              expected_dataset_manifest_hash: str | None = None,
              expected_fold_manifest_hash: str | None = None,
              expected_metric_spec_hash: str | None = None,
              expected_origin_manifest_hash: str | None = None,
              expected_code_commit: str | None = None):
    """Execute a single stage with all safety checks."""
    if stage not in STAGES:
        print(f"ERROR: Unknown stage '{stage}'. Use: {', '.join(STAGES)}")
        sys.exit(1)

    # Sealed-test requires explicit unseal
    if stage == "sealed-test":
        if not unseal:
            print("ERROR: sealed-test stage requires --unseal flag.")
            sys.exit(1)

    # Verify all hash guards before any stage execution
    print("Verifying hash guards...")
    verify_all_guards(
        stage,
        expected_config_hash=expected_config_hash,
        expected_code_commit=expected_code_commit,
        expected_manifest_sha=None,
        expected_dataset_manifest_sha=expected_dataset_manifest_hash,
        expected_fold_manifest_sha=expected_fold_manifest_hash,
        expected_metric_spec_sha=expected_metric_spec_hash,
        expected_origin_manifest_sha=expected_origin_manifest_hash,
    )
    print("  All hash guards passed.")

    # Load manifest and verify data-visibility boundary
    print(f"\n{'=' * 60}")
    print(f"STAGE: {stage.upper()}")
    print(f"{'=' * 60}")

    all_origins = []
    all_ledger = []
    all_scoring = []
    all_baseline = []

    for pair in PAIRS:
        m = load_manifest(pair)
        df = load_pair_d1(pair, stage)

        # Data-visibility assertion
        visibility_end = STAGE_VISIBILITY_END[stage]
        if len(df) > 0:
            max_ts = df["timestamp"].max()
            assert max_ts <= visibility_end, (
                f"Stage '{stage}' accessed data past visibility end {visibility_end}: "
                f"max timestamp {max_ts}"
            )
        print(f"  {pair}: {len(df)} accessible rows (visibility <= {visibility_end.date()})")

        # Get origins
        origins_df = get_possible_origins(df, STAGE_TARGET_SPLIT[stage])
        split = STAGE_TARGET_SPLIT[stage]
        print(f"  {pair}: {len(origins_df)} {split} origins")

        for _, row in origins_df.iterrows():
            origin_idx = int(row["origin_idx"])
            input_df = extract_input(df, origin_idx)
            target_df = extract_targets(df, origin_idx, split)

            origin_close = float(input_df["close"].iloc[-1])
            target_closes = target_df["close"].values.astype(float)
            target_timestamps = target_df["timestamp"].tolist()
            predicted = np.full(HORIZON, origin_close)  # placeholder for real inference

            all_origins.append({
                "pair": pair, "split": split, "origin_idx": origin_idx,
                "origin_timestamp": str(row["origin_timestamp"]),
            })

    # Count verification
    stage_counts = {}
    for s in ["development", "validation", "test"]:
        stage_counts[s] = sum(1 for o in all_origins if o["split"] == s)

    print(f"\n  Origin counts: dev={stage_counts.get('development', 0)}, "
          f"val={stage_counts.get('validation', 0)}, "
          f"test={stage_counts.get('test', 0)}")
    print(f"  Total origins: {len(all_origins)}")

    return all_origins


def main():
    args = parse_args()

    if args.stage == "count-only":
        run_count_only()
        return

    # For other stages, verify sealed-test unseal
    if args.stage == "sealed-test":
        if not args.unseal:
            print("ERROR: sealed-test requires --unseal")
            sys.exit(1)
        print(f"Sealed-test mode authorised with unseal flag.")
        print(f"Expected config hash: {args.expected_config_hash}")
        print(f"Expected code commit: {args.expected_code_commit}")

    run_stage(
        args.stage,
        unseal=args.unseal,
        expected_config_hash=args.expected_config_hash,
        expected_code_commit=args.expected_code_commit,
    )


if __name__ == "__main__":
    main()