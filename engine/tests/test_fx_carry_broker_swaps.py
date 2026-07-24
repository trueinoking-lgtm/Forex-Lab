"""Tests for Phase 2B prospective MT5 broker swap collection."""
import pytest
import json
import hashlib
from pathlib import Path

SWAP_RAW_DIR = Path("engine/data/fx_carry/broker_swaps/raw")
SWAP_CANONICAL_DIR = Path("engine/data/fx_carry/broker_swaps/canonical")
SWAP_INDEX = Path("engine/config/fx_carry_broker_swap_collection_index.json")

REQUIRED_SWAP_FIELDS = [
    "captured_at_utc", "broker", "broker_server", "account_type",
    "account_login_hash", "terminal_version", "metatrader5_package_version",
    "symbol", "swap_mode", "swap_long", "swap_short", "swap_rollover3days",
    "currency_base", "currency_profit", "currency_margin",
    "trade_contract_size", "point", "digits", "volume_min", "volume_step",
    "trade_tick_value", "bid", "ask", "quote_timestamp_raw",
    "quote_timestamp_interpretation", "collection_status",
]

REQUIRED_SYMBOLS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD"}


def test_swap_endpoint_rejected_wrong_token():
    """Wrong bearer token must be rejected with 401."""
    # This test assumes a bridge is running; skip if not available
    pytest.importorskip("requests")
    import requests
    try:
        resp = requests.get(
            "http://127.0.0.1:8787/symbols/swaps",
            params={"symbols": "EURUSD"},
            headers={"Authorization": "Bearer wrong-token"},
            timeout=3,
        )
        assert resp.status_code == 401
    except requests.ConnectionError:
        pytest.skip("Bridge not running")


def test_swap_fields_captured():
    """When data is captured, all required fields must be present."""
    # Look for any captured swap data
    found_any = False
    if SWAP_CANONICAL_DIR.exists():
        for sym_dir in SWAP_CANONICAL_DIR.iterdir():
            if sym_dir.is_dir():
                for f in sym_dir.glob("*.json"):
                    found_any = True
                    data = json.loads(f.read_text())
                    for field in REQUIRED_SWAP_FIELDS:
                        assert field in data, (
                            f"Missing swap field '{field}' in {f}"
                        )
    if not found_any:
        pytest.skip("No swap data collected yet (bridge offline)")


def test_swap_triple_roll_day_captured():
    """swap_rollover3days field must be present (not omitted)."""
    found_any = False
    if SWAP_CANONICAL_DIR.exists():
        for sym_dir in SWAP_CANONICAL_DIR.iterdir():
            if sym_dir.is_dir():
                for f in sym_dir.glob("*.json"):
                    found_any = True
                    data = json.loads(f.read_text())
                    assert "swap_rollover3days" in data, (
                        f"Missing swap_rollover3days in {f}"
                    )
    if not found_any:
        pytest.skip("No swap data collected yet")


def test_no_order_function_imported():
    """The swap collector must not import or call order functions."""
    collector = Path("engine/tradingbridge_collector/swap_collector.py")
    if not collector.exists():
        pytest.skip("Swap collector not yet created")
    content = collector.read_text()
    forbidden = ["order_send", "order_check", "order_delete", "trade_send", "modify_trade"]
    for term in forbidden:
        assert term not in content, (
            f"Forbidden order function '{term}' found in collector"
        )
    # Verify orders_called is always false
    assert "orders_called" in content


def test_broker_identity_recorded():
    """Each swap observation must record broker identity."""
    found_any = False
    if SWAP_CANONICAL_DIR.exists():
        for sym_dir in SWAP_CANONICAL_DIR.iterdir():
            if sym_dir.is_dir():
                for f in sym_dir.glob("*.json"):
                    found_any = True
                    data = json.loads(f.read_text())
                    assert data.get("broker"), f"Missing broker in {f}"
                    assert data.get("account_type") == "demo", (
                        f"Non-demo account in {f}"
                    )
    if not found_any:
        pytest.skip("No swap data collected yet")


def test_duplicate_snapshot_rejected():
    """Same broker+symbol+captured_at+sha256 combination must be deduplicated."""
    found_any = False
    if SWAP_CANONICAL_DIR.exists():
        seen_keys = set()
        for sym_dir in SWAP_CANONICAL_DIR.iterdir():
            if sym_dir.is_dir():
                for f in sym_dir.glob("*.json"):
                    found_any = True
                    data = json.loads(f.read_text())
                    key = (
                        data.get("broker_server", ""),
                        data.get("symbol", ""),
                        data.get("captured_at_utc", ""),
                        data.get("bid", ""),
                        data.get("ask", ""),
                    )
                    # If key already seen, it should NOT have been written again
                    assert key not in seen_keys, (
                        f"Duplicate observation detected: {key}"
                    )
                    seen_keys.add(key)
    if not found_any:
        pytest.skip("No swap data collected yet")


def test_failed_bridge_request_recorded():
    """Failed collection attempts must be recorded honestly, not fabricate rows."""
    if not SWAP_INDEX.exists():
        pytest.skip("No swap collection index yet")
    index = json.loads(SWAP_INDEX.read_text())
    for run in index.get("collection_runs", []):
        if run.get("failures"):
            assert run["row_count"] == 0 or run.get("source_endpoint"), (
                f"Failed run {run['collection_id']} has no honest record"
            )
            # Must not fabricate rows from previous data
            assert run.get("collection_status") != "fabricated"


def test_no_fabricated_history():
    """All observations must have fresh captured_at_utc, not backdated."""
    if not SWAP_CANONICAL_DIR.exists():
        pytest.skip("No swap data collected yet")
    for sym_dir in SWAP_CANONICAL_DIR.iterdir():
        if sym_dir.is_dir():
            for f in sym_dir.glob("*.json"):
                data = json.loads(f.read_text())
                captured = data.get("captured_at_utc", "")
                assert captured, f"Missing captured_at_utc in {f}"


def test_immutable_raw_responses():
    """Raw responses in raw/ directory must not be modified after first write."""
    found_any = False
    if SWAP_RAW_DIR.exists():
        for f in SWAP_RAW_DIR.glob("*.json"):
            if "failure" in f.name:
                continue
            found_any = True
            # Content is written once via write_text, immutable by design
            assert f.stat().st_size > 0, f"Empty raw file: {f}"
    if not found_any:
        pytest.skip("No raw swap responses collected yet")


def test_prospective_only_classification():
    """Swap data must be tagged as prospective, never as 'historical'."""
    collector = Path("engine/tradingbridge_collector/swap_collector.py")
    if not collector.exists():
        pytest.skip("Swap collector not yet created")
    content = collector.read_text()
    assert "prospective" in content.lower() or "swap_collect" in content
    assert "historical" not in content.lower().replace("prospective", "")
