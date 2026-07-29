#!/usr/bin/env python3
"""Verify the V3 resolved freeze manifest without importing research code."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    ROOT / "engine/docs/manifests/kronos_phase1_v3_resolved_freeze_manifest.json"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_bytes(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def fail(message: str) -> None:
    raise ValueError(message)


def main() -> int:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        freeze = manifest["protocol_freeze_commit"]
        if freeze != "4815c1b16eb18746d1ddfc717dcaa0e7f3fdf370":
            fail("protocol freeze commit mismatch")
        if manifest["protocol_freeze_timestamp"] != "2026-07-28T17:13:20Z":
            fail("protocol freeze timestamp mismatch")

        for item in manifest["frozen_files"]:
            path = item["path"]
            frozen = git_bytes(freeze, path)
            local = (ROOT / path).read_bytes()
            if frozen != local:
                fail(f"{path}: working file differs from protocol commit")
            if len(frozen) != item["byte_size"]:
                fail(f"{path}: byte size mismatch")
            if sha256(frozen) != item["sha256"]:
                fail(f"{path}: SHA-256 mismatch")
            blob = subprocess.run(
                ["git", "rev-parse", f"{freeze}:{path}"],
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.strip()
            if blob != item["git_blob"]:
                fail(f"{path}: Git blob mismatch")

        receipt = manifest["external_freeze_receipt"]
        receipt_bytes = (ROOT / receipt["path"]).read_bytes()
        if len(receipt_bytes) != receipt["byte_size"]:
            fail("external receipt byte size mismatch")
        if sha256(receipt_bytes) != receipt["sha256"]:
            fail("external receipt SHA-256 mismatch")
        committed_receipt = git_bytes(receipt["commit"], receipt["path"])
        if committed_receipt != receipt_bytes:
            fail("external receipt does not match its dedicated commit")

        for checkpoint in manifest["checkpoint_identities"].values():
            data = (ROOT / checkpoint["local_path"]).read_bytes()
            if len(data) != checkpoint["byte_size"]:
                fail(f"{checkpoint['local_path']}: byte size mismatch")
            if sha256(data) != checkpoint["sha256"]:
                fail(f"{checkpoint['local_path']}: SHA-256 mismatch")

        unresolved = manifest["unresolved_data_identities"]
        if any(unresolved[key] is not None for key in (
            "dataset_manifest_sha256",
            "fold_manifest_sha256",
            "origin_manifest_sha256",
        )):
            fail("prospective data identities must remain unresolved")
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"KRONOS_V3_FREEZE_MANIFEST_INVALID: {exc}", file=sys.stderr)
        return 1
    print("KRONOS_V3_FREEZE_MANIFEST_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
