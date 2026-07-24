"""Prospective MT5 broker swap data collector."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BRIDGE_BASE_URL = "http://127.0.0.1:8787"
BRIDGE_TOKEN = "aether-bridge-token"
BRIDGE_TIMEOUT = 10

SWAP_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
COLLECTION_DIR = Path("engine/data/fx_carry/broker_swaps/raw")
CANONICAL_DIR = Path("engine/data/fx_carry/broker_swaps/canonical")
INDEX_PATH = Path("engine/config/fx_carry_broker_swap_collection_index.json")


def swap_collect(symbols: list[str] | None = None) -> dict:
    symbols = symbols or SWAP_SYMBOLS
    COLLECTION_DIR.mkdir(parents=True, exist_ok=True)
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "collection_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "broker": "mt5_demo",
        "broker_server": None,
        "symbols_requested": symbols,
        "response_sha256": None,
        "row_count": 0,
        "failures": [],
        "source_endpoint": f"{BRIDGE_BASE_URL}/symbols/swaps",
        "safety_assertion": "orders_called=False",
        "orders_called": False,
    }

    try:
        import requests as req
        resp = req.get(
            f"{BRIDGE_BASE_URL}/symbols/swaps",
            params={"symbols": ",".join(symbols)},
            headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
            timeout=BRIDGE_TIMEOUT,
        )
    except ImportError:
        result["failures"].append({"type": "dependency_error", "detail": "requests not installed"})
        _record_failure(result)
        return result
    except Exception as e:
        result["failures"].append({"type": "connection_error", "detail": str(e)})
        _record_failure(result)
        return result

    if resp.status_code == 401:
        result["failures"].append({"type": "authentication_error", "detail": "wrong bearer token"})
        _record_failure(result)
        return result

    if resp.status_code != 200:
        result["failures"].append({"type": "http_error", "status": resp.status_code})
        _record_failure(result)
        return result

    data = resp.json()
    result["response_sha256"] = hashlib.sha256(resp.content).hexdigest()
    result["row_count"] = data.get("row_count", 0)
    result["broker_server"] = "connected" if data.get("row_count", 0) > 0 else None
    result["orders_called"] = data.get("orders_called", False)

    for f in data.get("failures", []):
        result["failures"].append(f)

    raw_path = COLLECTION_DIR / f"swap_collection_{result['collection_id']}.json"
    raw_path.write_text(json.dumps(data, indent=2))

    for row in data.get("results", []):
        _append_canonical(row)

    _update_index(result)
    return result


def _append_canonical(row: dict) -> None:
    sym = row["symbol"]
    symbol_dir = CANONICAL_DIR / sym
    symbol_dir.mkdir(parents=True, exist_ok=True)
    dedup_key = f"{row.get('broker_server','')}|{sym}|{row.get('captured_at_utc','')}|{row.get('bid','')}|{row.get('ask','')}"
    dedup_id = hashlib.sha256(dedup_key.encode()).hexdigest()[:16]
    filepath = symbol_dir / f"{dedup_id}.json"
    if not filepath.exists():
        filepath.write_text(json.dumps(row, indent=2, sort_keys=True))


def _record_failure(result: dict) -> None:
    fail_path = COLLECTION_DIR / f"failure_{result['collection_id']}.json"
    fail_path.write_text(json.dumps(result, indent=2, sort_keys=True))


def _update_index(result: dict) -> None:
    if INDEX_PATH.exists():
        index = json.loads(INDEX_PATH.read_text())
    else:
        index = {"collection_runs": [], "total_successful": 0, "total_failed": 0}

    index["collection_runs"].append({
        "collection_id": result["collection_id"],
        "timestamp_utc": result["timestamp_utc"],
        "symbols_requested": result["symbols_requested"],
        "row_count": result["row_count"],
        "failures": result["failures"],
        "source_endpoint": result["source_endpoint"],
        "response_sha256": result["response_sha256"],
        "orders_called": result["orders_called"],
        "bridge_commit": _get_bridge_commit(),
    })
    index["total_successful"] += 1 if not result["failures"] else 0
    index["total_failed"] += 1 if result["failures"] else 0
    INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")


def _get_bridge_commit() -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%H"],
            cwd=Path("remote-mt5-bridge"),
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


if __name__ == "__main__":
    result = swap_collect()
    print(json.dumps(result, indent=2))
    sys.exit(0 if not result["failures"] else 1)
