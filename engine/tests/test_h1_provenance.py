"""Tests for the canonical MT5 H1 provenance verifier."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import verify_h1_provenance as provenance  # noqa: E402
from src.timestamp_validation import guard_session_dependent_strategy  # noqa: E402


EXPECTED_SYMBOLS = ("EURUSD", "AUDUSD", "GBPUSD", "USDJPY")
EXPECTED_TIMESTAMP_FIELDS = {
    "timestamp_semantics": "BROKER_SERVER_BAR_OPEN_TIME",
    "timestamp_timezone_label_original": "UTC_INCORRECT",
    "historical_offset_policy": "UNRESOLVED",
    "timestamp_research_restrictions": "exact_session_mapping_not_authorised",
    "observed_server_offset_at_probe": "+03:00",
    "observed_offset_seconds": 10800,
    "probe_timestamp_utc": "2026-07-24",
    "timezone_probe_file": "mt5_time_probe_output.json",
}


def _write_dataset(data_dir: Path, symbol: str, csv: bytes = b"time,close\n1,2\n") -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"raw_mt5_{symbol}_1h.csv").write_bytes(csv)
    (data_dir / "mt5_time_probe_output.json").write_text("{}", encoding="utf-8")
    manifest = {
        **EXPECTED_TIMESTAMP_FIELDS,
        "file_sha256": hashlib.sha256(csv).hexdigest(),
    }
    path = data_dir / f"raw_mt5_{symbol}_1h.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _point_verifier_at(monkeypatch, data_dir: Path) -> None:
    monkeypatch.setattr(provenance, "ENGINE_DIR", data_dir.parent)
    monkeypatch.setattr(provenance, "DATA_DIR", data_dir)


def test_all_four_canonical_manifests_have_exact_names_and_verify():
    assert provenance.SYMBOLS == EXPECTED_SYMBOLS

    for symbol in EXPECTED_SYMBOLS:
        expected = provenance.DATA_DIR / f"raw_mt5_{symbol}_1h.manifest.json"
        assert provenance.canonical_manifest_path(symbol) == expected
        assert expected.is_file()
        _, manifest = provenance.load_canonical_manifest(symbol)
        assert "csv_sha256" not in manifest
        assert {key: manifest.get(key) for key in EXPECTED_TIMESTAMP_FIELDS} == (
            EXPECTED_TIMESTAMP_FIELDS
        )
        evidence = provenance.verify_symbol(symbol)
        assert any(f"{symbol} CSV SHA256: PASS" in line for line in evidence)
        assert any(f"{symbol} SESSION GUARD: PASS (blocked)" == line for line in evidence)


def test_csv_sha256_is_checked_against_file_sha256(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    manifest_path = _write_dataset(data_dir, "EURUSD", b"canonical csv")
    _point_verifier_at(monkeypatch, data_dir)

    provenance.verify_symbol("EURUSD")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["file_sha256"] == hashlib.sha256(b"canonical csv").hexdigest()
    assert "csv_sha256" not in manifest

    manifest["file_sha256"] = hashlib.sha256(b"different csv").hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="CSV SHA256 mismatch"):
        provenance.verify_symbol("EURUSD")


def test_csv_sha256_field_is_forbidden_and_never_introduced(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    manifest_path = _write_dataset(data_dir, "EURUSD")
    original = manifest_path.read_bytes()
    _point_verifier_at(monkeypatch, data_dir)

    provenance.verify_symbol("EURUSD")
    assert manifest_path.read_bytes() == original
    assert "csv_sha256" not in json.loads(original)

    manifest = json.loads(original)
    manifest["csv_sha256"] = manifest["file_sha256"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden csv_sha256"):
        provenance.verify_symbol("EURUSD")


@pytest.mark.parametrize("field,wrong", [
    ("timestamp_semantics", "UTC"),
    ("timestamp_timezone_label_original", "UTC"),
    ("historical_offset_policy", "RESOLVED"),
    ("timestamp_research_restrictions", None),
    ("observed_server_offset_at_probe", "+02:00"),
    ("observed_offset_seconds", 10800.0),
    ("probe_timestamp_utc", "2026-07-23"),
    ("timezone_probe_file", "other.json"),
])
def test_every_timestamp_semantics_field_is_required(
    tmp_path, monkeypatch, field, wrong
):
    data_dir = tmp_path / "data"
    manifest_path = _write_dataset(data_dir, "EURUSD")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = wrong
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _point_verifier_at(monkeypatch, data_dir)

    with pytest.raises((ValueError, FileNotFoundError), match=field):
        provenance.verify_symbol("EURUSD")


def test_unresolved_offset_guard_blocks_session_dependent_research(tmp_path):
    data_dir = tmp_path / "data"
    _write_dataset(data_dir, "EURUSD")

    with pytest.raises(ValueError, match="Session-dependent strategies not allowed"):
        guard_session_dependent_strategy(data_dir, "EURUSD", "1h")


def test_archive_and_temporary_manifest_decoys_are_never_used(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    for symbol in EXPECTED_SYMBOLS:
        _write_dataset(data_dir, symbol, f"{symbol}\n".encode())

    decoys = [
        data_dir / "archive" / "raw_mt5_NZDUSD_1h.manifest.json",
        data_dir / "archive" / "raw_mt5_EURUSD_1h.manifest.json",
        data_dir / "raw_mt5_EURUSD_1h.manifest.corrected.json",
        data_dir / "raw_mt5_GBPUSD_1h.manifest.updated.json",
        data_dir / "raw_mt5_AUDUSD_1h.manifest.json.tmp",
    ]
    for decoy in decoys:
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_text("{malformed decoy", encoding="utf-8")

    _point_verifier_at(monkeypatch, data_dir)
    assert all(provenance.verify_symbol(symbol) for symbol in EXPECTED_SYMBOLS)
    assert provenance.main() == 0


def test_nonexistent_and_unsupported_symbols(tmp_path, monkeypatch):
    _point_verifier_at(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="unsupported symbol"):
        provenance.canonical_manifest_path("NZDUSD")
    with pytest.raises(FileNotFoundError, match="canonical manifest not found"):
        provenance.load_canonical_manifest("EURUSD")


@pytest.mark.parametrize("contents,error", [
    ("{not json", json.JSONDecodeError),
    ("[]", ValueError),
])
def test_malformed_canonical_manifests(tmp_path, monkeypatch, contents, error):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "raw_mt5_EURUSD_1h.manifest.json").write_text(
        contents, encoding="utf-8"
    )
    _point_verifier_at(monkeypatch, data_dir)

    with pytest.raises(error):
        provenance.load_canonical_manifest("EURUSD")
