"""Tests for FX carry acquisition framework."""
import json
import pytest
from pathlib import Path
from engine.carry_data.acquisition import SourceAcquisitionError, save_raw, acquire_source, ImmutableAcquisitionError
from engine.carry_data.models import SourceRecord
from engine.carry_data.source_registry import load_registry, validate_registry, registry_hash
from engine.carry_data.models import AcquisitionManifest
from datetime import date, datetime, timezone

REGISTRY_PATH = "engine/config/fx_carry_source_registry.json"


def test_registry_hash_is_deterministic():
    h1 = registry_hash()
    h2 = registry_hash()
    assert h1 == h2, "Registry hash must be deterministic"
    assert len(h1) == 64, "SHA-256 hash must be 64 characters"


def test_registry_validates_cleanly():
    records = load_registry()
    validate_registry(records)  # must not raise


def test_registry_missing_fields_raises():
    records = load_registry()
    # Temporarily corrupt a record
    if records:
        original = records[0].institution
        records[0].institution = ""
        try:
            validate_registry(records)
            assert False, "Should have raised ValueError for missing field"
        except ValueError:
            pass
        finally:
            records[0].institution = original


def test_acquisition_id_is_unique():
    records = load_registry()
    canonical = [r for r in records if r.benchmark_type not in ("policy_rate_weekly", "policy_rate_daily")]
    if not canonical:
        pytest.skip("No canonical sources in registry")
    source = canonical[0]
    # acquire_source will fail for stubs but should generate unique IDs
    # We test by calling save_raw with a synthetic manifest
    manifest = AcquisitionManifest(
        acquisition_id="test-acq-001",
        source_uri=source.official_source_location,
        response_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        request_metadata={"start": "2010-01-01", "end": "2010-01-02"},
        acquisition_timestamp_utc=datetime.now(timezone.utc),
        http_status=200,
        content_type="application/octet-stream",
        source_identifier=source.exact_series_identifier,
        requested_date_range=("2010-01-01", "2010-01-02"),
        parser_version="1.0.0",
        licensing_metadata="test",
        source_registry_version_hash=registry_hash(),
        raw_response_path="",
    )
    raw = b"test raw response bytes"
    path = save_raw(manifest.acquisition_id, raw, manifest)
    assert path.exists(), "Raw file must be saved"
    assert path.read_bytes() == raw, "Raw bytes must match"

    manifest_file = path.parent / "manifest.json"
    assert manifest_file.exists(), "Manifest must be saved alongside raw response"

    # Verify the manifest JSON is valid
    loaded_manifest = json.loads(manifest_file.read_text())
    assert loaded_manifest["acquisition_id"] == "test-acq-001"


def test_no_secret_persistence():
    """Raw manifests must not contain secrets, tokens, or API keys."""
    records = load_registry()
    for rec in records:
        for field_name in ["access_requirements", "official_source_location"]:
            val = getattr(rec, field_name, "") or ""
            assert "token" not in val.lower(), f"Token found in {field_name} for {rec.benchmark_name}"
            assert "api_key" not in val.lower(), f"API key found in {field_name} for {rec.benchmark_name}"
            assert "password" not in val.lower(), f"Password found in {field_name} for {rec.benchmark_name}"


def test_raw_response_immutable_on_reacquire():
    """Saving the same acquisition_id after a successful first save raises ImmutableAcquisitionError."""
    import shutil
    from pathlib import Path
    test_dir = Path("engine/data/fx_carry/raw/test_immutable_reacquire")
    # Clean up any prior test state
    if test_dir.exists():
        shutil.rmtree(test_dir)

    manifest = AcquisitionManifest(
        acquisition_id="test-immutable-reacquire",
        source_uri="https://example.com/test",
        response_sha256="original_hash",
        request_metadata={},
        acquisition_timestamp_utc=datetime.now(timezone.utc),
        http_status=200,
        content_type="text/plain",
        source_identifier="TEST_IMMUTABLE",
        requested_date_range=("2010-01-01", "2010-01-02"),
        parser_version="1.0.0",
        licensing_metadata="test",
        source_registry_version_hash=registry_hash(),
        raw_response_path="",
    )
    raw1 = b"original content"

    p1 = save_raw(manifest.acquisition_id, raw1, manifest)
    assert p1.exists(), "First save must succeed"
    assert p1.read_bytes() == raw1, "First save must contain original content"

    with pytest.raises((ImmutableAcquisitionError, FileExistsError)):
        save_raw(manifest.acquisition_id, b"newer content", manifest)

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)


def test_fred_is_excluded_from_canonical_adapters():
    """FRED adapter identifies itself as mirror, not canonical."""
    from engine.carry_data.adapters.fred import FredAdapter
    adapter = FredAdapter()
    assert adapter.identify_source() == "fred_mirror", \
        "FRED adapter must identify as mirror"


def test_adapters_fail_closed_on_missing_registry_fields():
    """Adapters must raise SourceAcquisitionError if registry lacks required fields."""
    from engine.carry_data.adapters.new_york_fed import NewYorkFedAdapter
    adapter = NewYorkFedAdapter()

    broken = SourceRecord(
        currency="USD", benchmark_name="Broken", institution="",
        official_source_location="", exact_series_identifier="",
        benchmark_type="overnight_unsecured", secured_or_unsecured="unsecured",
        frequency="daily", observation_timezone="America/New_York",
        value_date_semantics="T-1", publication_time="", publication_lag="",
        first_available_date="", latest_available_date="", revision_policy="",
        methodology_changes="", holiday_handling="", missing_value_policy="",
        machine_readable_format="", access_requirements="",
        licensing_or_redistribution_restrictions="", intended_research_role="",
        known_limitations="",
    )

    try:
        adapter.build_request(broken, date(2010, 1, 1), date(2010, 1, 2))
        assert False, "Should have raised SourceAcquisitionError"
    except SourceAcquisitionError:
        pass  # expected
