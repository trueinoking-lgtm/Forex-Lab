"""Append-only, deterministic registry for offline research experiments.

This module only records research artifacts.  It has no dependency on signal or
execution code and deliberately rejects secret-shaped fields.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
REQUIRED_RESULT_METRICS = (
    "total_return", "max_drawdown", "profit_factor", "win_rate", "trade_count",
    "score", "robustness", "oos_return",
)
SECRET_FRAGMENTS = ("token", "password", "passwd", "secret", "private_key", "credential", ".env")
VALID_STATUSES = {"rejected", "research_candidate", "watcher_eligible"}


class RegistryConflict(ValueError):
    """Raised when an existing immutable experiment would be changed."""


def _safe(value: Any, path: str = "record") -> Any:
    """Return strict-JSON primitives and reject secret-shaped keys."""
    if isinstance(value, Mapping):
        out = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if any(fragment in lowered for fragment in SECRET_FRAGMENTS):
                raise ValueError(f"secret-shaped field is not permitted: {path}.{key}")
            out[key] = _safe(item, f"{path}.{key}")
        return out
    if isinstance(value, (list, tuple)):
        return [_safe(item, path) for item in value]
    if hasattr(value, "item"):
        return _safe(value.item(), path)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported value at {path}: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(_safe(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit(repo: Path | str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), check=True,
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def gate_outcomes(metrics: Mapping[str, Any]) -> dict[str, bool]:
    """Apply the locked research gates; missing/non-finite values fail closed."""
    def passes(name: str, predicate) -> bool:
        value = metrics.get(name)
        try:
            return bool(math.isfinite(float(value)) and predicate(float(value)))
        except (TypeError, ValueError):
            return False

    return {
        "score_gte_40": passes("score", lambda value: value >= 40.0),
        "robustness_gte_0_3": passes("robustness", lambda value: value >= 0.3),
        "oos_return_gt_0": passes("oos_return", lambda value: value > 0.0),
        "profit_factor_gte_1_3": passes("profit_factor", lambda value: value >= 1.3),
    }


def build_experiment(payload: Mapping[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    """Normalize a record and assign an ID from its timestamp-free contents."""
    clean = _safe(dict(payload))
    metrics = clean.get("performance_metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    complete = all(metrics.get(name) is not None for name in REQUIRED_RESULT_METRICS)
    gates = gate_outcomes(metrics)
    reasons = list(clean.get("rejection_reasons") or [])
    missing = [name for name in REQUIRED_RESULT_METRICS if metrics.get(name) is None]
    if missing:
        reasons.append("incomplete result: missing " + ", ".join(missing))
    for name, passed in gates.items():
        if not passed and not missing:
            reasons.append("failed gate: " + name)

    if complete and all(gates.values()):
        status = clean.get("final_status", "watcher_eligible")
    elif complete:
        status = clean.get("final_status", "rejected")
    else:
        status = "rejected"
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid final_status: {status}")
    if status == "watcher_eligible" and not (complete and all(gates.values())):
        raise ValueError("watcher_eligible requires every locked gate to pass")

    record = {
        "schema_version": SCHEMA_VERSION,
        **clean,
        "performance_metrics": metrics,
        "execution_gate_outcomes": gates,
        "final_status": status,
        "rejection_reasons": sorted(set(reasons)),
    }
    record.pop("experiment_id", None)
    record.pop("creation_timestamp", None)
    identity = canonical_json(record)
    record["experiment_id"] = "exp_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    timestamp = created_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    record["creation_timestamp"] = timestamp
    return _safe(record)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(_safe(value), indent=2, sort_keys=True, ensure_ascii=False,
                         allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render_markdown(records: list[Mapping[str, Any]]) -> str:
    lines = ["# Research experiment registry", "", "Append-only experiment audit summary.", ""]
    for record in records:
        lines.extend([
            f"## {record['experiment_id']}", "",
            f"- Created: {record['creation_timestamp']}",
            f"- Strategy: {record.get('strategy_name')}",
            f"- Symbol / timeframe: {record.get('symbol')} / {record.get('timeframe')}",
            f"- Git commit: {record.get('git_commit_hash')}",
            f"- Status: **{record.get('final_status')}**", "",
        ])
        reasons = record.get("rejection_reasons") or []
        if reasons:
            lines.extend(["Rejection reasons:", ""] + [f"- {reason}" for reason in reasons] + [""])
    return "\n".join(lines).rstrip() + "\n"


def register_experiment(payload: Mapping[str, Any], store_path: Path | str,
                        markdown_path: Path | str | None = None,
                        *, created_at: str | None = None) -> dict[str, Any]:
    """Atomically append once; repeated identical registrations are idempotent."""
    store = Path(store_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    lock_path = store.with_suffix(store.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Hermes/Linux supplies fcntl
            pass
        container = json.loads(store.read_text()) if store.exists() else {
            "schema_version": SCHEMA_VERSION, "experiments": [],
        }
        proposed = build_experiment(payload, created_at=created_at)
        for existing in container.get("experiments", []):
            if existing.get("experiment_id") == proposed["experiment_id"]:
                # Creation time is intentionally not identity-bearing.
                lhs = {k: v for k, v in existing.items() if k != "creation_timestamp"}
                rhs = {k: v for k, v in proposed.items() if k != "creation_timestamp"}
                if canonical_json(lhs) != canonical_json(rhs):
                    raise RegistryConflict(f"immutable experiment conflict: {proposed['experiment_id']}")
                return existing
        container["experiments"].append(proposed)
        _atomic_json(store, container)
        if markdown_path is not None:
            markdown = Path(markdown_path)
            markdown.parent.mkdir(parents=True, exist_ok=True)
            text = render_markdown(container["experiments"])
            fd, temporary = tempfile.mkstemp(prefix=markdown.name + ".", suffix=".tmp",
                                             dir=str(markdown.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, markdown)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return proposed
