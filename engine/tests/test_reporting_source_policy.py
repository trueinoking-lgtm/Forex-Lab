import json
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
CANONICAL_SHA = "4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2"
REQUIRED_LINES = (
    "Report class: short_window_yfinance_advisory",
    "Watcher eligible strategies: 0",
    "Canonical research source: MT5 D1",
    "Advisory source: yfinance D1",
    "Sources differ: YES",
    "All researched families: REJECTED",
    "No signal created",
    "No order placed",
)


def run_report(tmp_path, canonical_path=None, check=True):
    db_path = tmp_path / "forex_lab.db"
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript((APP / "schema.sql").read_text())
    con.close()
    env = {**os.environ, "FOREX_LAB_DB": str(db_path), "AETHER_RESULTS_DIR": str(results)}
    if canonical_path:
        env["AETHER_CANONICAL_RESEARCH_PATH"] = str(canonical_path)
    proc = subprocess.run(
        ["node", "scripts/report_payload.mjs"], cwd=APP, env=env,
        check=check, capture_output=True, text=True,
    )
    payload_path = results / "daily_report_payload.json"
    return proc, json.loads(payload_path.read_text()) if payload_path.exists() else None


def test_yfinance_advisory_not_canonical(tmp_path):
    _, payload = run_report(tmp_path)
    advisory = payload["source_policy"]["advisory"]
    canonical = payload["source_policy"]["canonical"]
    assert advisory["provider"] == "yfinance"
    assert advisory["label"] == "short_window_yfinance_advisory"
    assert canonical["provider"] == "MT5"
    assert canonical["fingerprint"] == CANONICAL_SHA
    assert advisory["provider"] != canonical["provider"]
    assert advisory["label"] != "canonical_long_history_research"


@pytest.mark.parametrize("field,value", [
    ("provider", "other"), ("timeframe", "H1"), ("start", "2020-01-02"),
    ("end", "2021-01-02"), ("fingerprint", "other"),
])
def test_source_comparison_detects_mismatch(field, value):
    script = f"""
      import {{ sourcesDiffer }} from './scripts/reporting_source_policy.mjs';
      const left = {{provider:'MT5',timeframe:'D1',start:'2020-01-01',end:'2021-01-01',fingerprint:'same'}};
      const right = {{...left, {field}: {json.dumps(value)}}};
      process.stdout.write(sourcesDiffer(left, right));
    """
    proc = subprocess.run(["node", "--input-type=module", "-e", script], cwd=APP,
                          check=True, capture_output=True, text=True)
    assert proc.stdout == "YES"


def test_missing_canonical_fingerprint_fails(tmp_path):
    source = json.loads((ROOT / "engine/results/range_mr_period_regime.json").read_text())
    source["input"].pop("sha256")
    broken = tmp_path / "canonical_without_sha.json"
    broken.write_text(json.dumps(source))
    proc, payload = run_report(tmp_path, broken, check=False)
    assert proc.returncode != 0
    assert payload is None
    assert "canonical fingerprint missing or mismatch" in proc.stderr


def test_watcher_eligibility_separate_from_canonical(tmp_path):
    _, payload = run_report(tmp_path)
    assert payload["watcher_eligible"] == 0
    assert "watcher_eligible" not in payload["source_policy"]["canonical"]
    assert payload["canonical_research_fingerprint"] == CANONICAL_SHA
    for line in REQUIRED_LINES:
        assert line in payload["message"]
