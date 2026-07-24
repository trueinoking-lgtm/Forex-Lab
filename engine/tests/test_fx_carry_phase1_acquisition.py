"""Tests for Phase 1B official data acquisition."""
import json
import hashlib
from pathlib import Path
import pytest

RAW_BASE = Path("engine/data/fx_carry/raw")
ACQUISITION_SUMMARY = Path("engine/data/fx_carry/acquisition_summary_2026-07-24.json")


def test_acquisition_summary_exists():
    assert ACQUISITION_SUMMARY.exists(), "Acquisition summary report must exist"


def test_acquisition_summary_valid_json():
    data = json.loads(ACQUISITION_SUMMARY.read_text())
    assert "results" in data
    assert len(data["results"]) >= 1


def test_usd_effr_acquired():
    """USD EFFR must be acquired successfully with correct metadata."""
    data = json.loads(ACQUISITION_SUMMARY.read_text())
    effr = [r for r in data["results"] if r["currency"] == "USD" and "EFFR" in r["benchmark"]]
    assert len(effr) == 1, "Must have exactly one USD EFFR result"
    r = effr[0]
    assert r["status"] == "SUCCESS"
    assert r["observations"] > 0
    assert r.get("sha256") is not None
    assert r.get("acquisition_id") is not None
    assert r["first_observation"] >= "2010-01-01"


def test_usd_sofr_acquired():
    """USD SOFR must be acquired successfully."""
    data = json.loads(ACQUISITION_SUMMARY.read_text())
    sofr = [r for r in data["results"] if r["currency"] == "USD" and "SOFR" in r["benchmark"]]
    assert len(sofr) == 1
    r = sofr[0]
    assert r["status"] == "SUCCESS"
    assert r["observations"] > 0
    assert r["first_observation"] >= "2013-04-03"  # SOFR began 2013-04-03


def test_effr_raw_response_exists():
    """Raw EFFR response file must be preserved on disk."""
    found = False
    for inst_dir in RAW_BASE.iterdir():
        for bench_dir in inst_dir.iterdir():
            for acq_dir in bench_dir.iterdir():
                raw_file = acq_dir / "raw_response.bin"
                manifest_file = acq_dir / "manifest.json"
                if raw_file.exists() and manifest_file.exists():
                    manifest = json.loads(manifest_file.read_text())
                    if manifest.get("source_identifier") in ("EFFR", "treasury_effective_rate"):
                        assert raw_file.stat().st_size > 0, "Raw response must not be empty"
                        found = True
    assert found, "EFFR raw response not found on disk"


def test_sofr_raw_response_exists():
    """Raw SOFR response file must be preserved on disk."""
    found = False
    for inst_dir in RAW_BASE.iterdir():
        for bench_dir in inst_dir.iterdir():
            for acq_dir in bench_dir.iterdir():
                raw_file = acq_dir / "raw_response.bin"
                manifest_file = acq_dir / "manifest.json"
                if raw_file.exists() and manifest_file.exists():
                    manifest = json.loads(manifest_file.read_text())
                    if manifest.get("source_identifier") in ("SOFR", "secured_overnight_financing_rate"):
                        assert raw_file.stat().st_size > 0
                        found = True
    assert found, "SOFR raw response not found on disk"


def test_no_policy_rates_in_canonical_acquisitions():
    """Policy-rate fallbacks must not be acquired as canonical data."""
    data = json.loads(ACQUISITION_SUMMARY.read_text())
    canonical = [r for r in data["results"] if r["status"] == "SUCCESS"]
    policy_rates = [r for r in canonical if r["benchmark"] in (
        "ECB Deposit Facility Rate", "Bank Rate", "BOJ Policy Rate", "RBA Cash Rate"
    )]
    assert len(policy_rates) == 0, "Policy rates must not be in canonical acquisitions"


def test_source_files_have_valid_sha256():
    """Raw response SHA-256 values in the summary must match actual files."""
    if not ACQUISITION_SUMMARY.exists():
        pytest.skip("No acquisition summary yet")

    data = json.loads(ACQUISITION_SUMMARY.read_text())
    for r in data["results"]:
        if r["status"] != "SUCCESS" or "sha256" not in r:
            continue
        # Find the raw file
        sha_expected = r["sha256"]
        for inst_dir in RAW_BASE.iterdir():
            for bench_dir in inst_dir.iterdir():
                for acq_dir in bench_dir.iterdir():
                    raw_file = acq_dir / "raw_response.bin"
                    manifest_file = acq_dir / "manifest.json"
                    if raw_file.exists() and manifest_file.exists():
                        manifest = json.loads(manifest_file.read_text())
                        if manifest.get("response_sha256") == sha_expected:
                            actual_sha = hashlib.sha256(raw_file.read_bytes()).hexdigest()
                            assert actual_sha == sha_expected, \
                                f"SHA-256 mismatch for {r['benchmark']}: expected {sha_expected}, got {actual_sha}"


def test_ecb_sources_blocked_not_failed():
    """ECB sources must be documented as blocked due to infrastructure, not failed due to source quality."""
    data = json.loads(ACQUISITION_SUMMARY.read_text())
    eur_blocked = [r for r in data["results"]
                   if r["currency"] == "EUR" and r["status"] == "BLOCKED"]
    for r in eur_blocked:
        assert "DNS" in r.get("reason", "") or "unreachable" in r.get("reason", "").lower(), \
            f"ECB source must be blocked by infrastructure, got: {r.get('reason')}"
