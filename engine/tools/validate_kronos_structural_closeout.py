"""Machine validator for Kronos structural closeout bundle."""
import sys, json, hashlib
from pathlib import Path
import pandas as pd

BASE = Path("engine/artifacts/kronos_phase1_v2/structural_closeout_20260727")
FAILURES = []

def check(name, condition, detail=""):
    if not condition:
        FAILURES.append(f"{name}: {detail or 'FAILED'}")

# 1. Every required artifact exists
required = [
    "closeout_report.md", "stress_run_1.json", "stress_run_2.json",
    "stress_run_1_predictions.csv", "stress_run_2_predictions.csv",
    "stress_run_1.log", "stress_run_2.log",
    "implementation_tests_run_1.log", "implementation_tests_run_2.log",
    "implementation_tests_run_3.log", "implementation_tests_run_4.log",
    "implementation_tests_run_5.log", "random_order_tests.json",
    "production_readiness.log", "replay_tamper_results.json",
    "numerical_gates.json", "environment_manifest.json", "evidence_manifest.json",
    "validation_report.json",
]
for name in required:
    check(f"artifact_exists_{name}", (BASE / name).exists(), f"{name} missing")

# 2. Evidence manifest SHA-256 matches every file
manifest = json.loads((BASE / "evidence_manifest.json").read_text())
for fname, info in manifest.items():
    fpath = BASE / fname
    if fpath.exists():
        actual_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
        check(f"manifest_sha_{fname}", actual_sha == info["sha256"],
              f"expected {info['sha256']}, got {actual_sha}")

# 3. Each stress run has exactly 200 contexts, 1000 rows
for run in ["stress_run_1", "stress_run_2"]:
    df_path = BASE / f"{run}_predictions.csv"
    if df_path.exists():
        df = pd.read_csv(df_path)
        check(f"{run}_rows", len(df) == 1000, f"got {len(df)} rows")
        contexts = df["context_id"].nunique()
        check(f"{run}_contexts", contexts == 200, f"got {contexts} contexts")
        schemas = set(df["schema"].unique())
        check(f"{run}_schemas", schemas == {"OHLC", "OHLCV+amount"}, f"got {schemas}")
        horizons = set(df["horizon"].unique())
        check(f"{run}_horizons", horizons == {1,2,3,4,5}, f"got {horizons}")
        predictor_classes = set(df["predictor_class"].unique())
        check(f"{run}_real_predictor", predictor_classes == {"KronosPredictor"}, f"got {predictor_classes}")
        check(f"{run}_no_fake", "FakeKronosPredictor" not in predictor_classes, "")
        check(f"{run}_raw_cols", all(c in df.columns for c in ["raw_open","raw_high","raw_low","raw_close"]), "missing raw columns")
        check(f"{run}_proj_cols", all(c in df.columns for c in ["projected_open","projected_high","projected_low","projected_close"]), "missing projected columns")
        check(f"{run}_proj_valid_100", bool(df["projected_valid"].all()), "projected validity < 100%")

# 4. Numerical gates have concrete values
gates = json.loads((BASE / "numerical_gates.json").read_text())
for mode, gate_list in gates.items():
    for g in gate_list:
        check(f"gate_{g['gate_id']}_has_threshold", g.get("numerical_threshold") is not None, f"{g['gate_id']} missing threshold")

# 5. All five implementation runs passed
for i in range(1, 6):
    log = (BASE / f"implementation_tests_run_{i}.log").read_text()
    check(f"impl_run_{i}_passed", "23 passed" in log and "0 failed" in log, f"run {i} summary")

# 6. All ten random-order runs passed
random_tests = json.loads((BASE / "random_order_tests.json").read_text())
check("random_10_seeds", len(random_tests) == 10, f"got {len(random_tests)}")

# 7. Production readiness remains blocked
prod_log = (BASE / "production_readiness.log").read_text() if (BASE / "production_readiness.log").exists() else ""
check("prod_readiness_blocked", "blocked" in prod_log.lower() or "absent" in prod_log.lower(), "readiness not blocked")

# 8. Gate document SHA-256 matches
import subprocess
actual_gate_sha = subprocess.check_output(["sha256sum", "docs/kronos_v2_proposed_gates.md"]).decode().split()[0]
expected_gate_sha = "35bbdde1f8571d7554c90fed3ce900db289e7199c3f5f55f0326e52e20cd66"
check("gate_doc_sha", actual_gate_sha == expected_gate_sha, f"expected {expected_gate_sha}, got {actual_gate_sha}")

# 9. Replay tamper results recorded
replay_exists = (BASE / "replay_tamper_results.json").exists()
check("replay_tamper_exists", replay_exists, "replay_tamper_results.json missing")

# 10. closeout_report.md reproduces gate doc verbatim
closeout = (BASE / "closeout_report.md").read_text()
gate_sha_in_report = "35bbdde1f8571d7554c90fed3ce900db289e7199c3f5f55f0326e52e20cd66"
check("closeout_gate_sha", gate_sha_in_report in closeout, "gate SHA not in closeout report")

if FAILURES:
    for f in FAILURES:
        print(f"FAIL: {f}", file=sys.stderr)
    print("KRONOS_STRUCTURAL_CLOSEOUT_INVALID")
    sys.exit(1)
else:
    print("KRONOS_STRUCTURAL_CLOSEOUT_VALID")
    sys.exit(0)
