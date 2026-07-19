"""Append-only prospective forward-validation ledger (research only)."""
from __future__ import annotations
import hashlib, json, os, tempfile
from pathlib import Path

REQUIRED = ("prediction", "strategy_version", "signal_timestamp",
            "expected_execution", "actual_outcome", "costs", "passed_all_gates_at_creation")


def freeze_policy(strategy_code: bytes, parameters: dict, gates: dict, costs: dict,
                  data_cutoff_timestamp: str) -> dict:
    canonical = lambda x: json.dumps(x, sort_keys=True, separators=(",", ":"))
    return {"strategy_code_hash": hashlib.sha256(strategy_code).hexdigest(),
            "parameter_hash": hashlib.sha256(canonical(parameters).encode()).hexdigest(),
            "gate_definitions": gates, "cost_scenarios": costs,
            "data_cutoff_timestamp": data_cutoff_timestamp,
            "starts": "next fully closed candle"}


def append_entry(path, entry):
    missing = [k for k in REQUIRED if k not in entry]
    if missing: raise ValueError("missing forward-validation fields: " + ", ".join(missing))
    path = Path(path); current = json.loads(path.read_text()) if path.exists() else {"entries": []}
    identity = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
    if any(x.get("entry_id") == identity for x in current["entries"]): return current
    current["entries"].append({"entry_id": identity, **entry})
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w") as f: json.dump(current, f, indent=2, sort_keys=True); f.write("\n")
        os.replace(tmp, path)
    finally: Path(tmp).unlink(missing_ok=True)
    return current
