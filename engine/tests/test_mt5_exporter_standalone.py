"""Regression test: mt5_history_export.py must be standalone on the Windows PC.

It must run with ONLY the Python stdlib, pandas, and MetaTrader5 -- no imports
from engine-local modules (run_acquire_data.py, src/*). Copying just the single
file into an isolated directory and invoking --help must succeed (exit 0) without
any engine context present.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

EXPORTER = os.path.join(os.path.dirname(__file__), "..", "mt5_history_export.py")


@pytest.mark.skipif(
    not os.path.exists(EXPORTER),
    reason="exporter not present in this checkout",
)
def test_exporter_is_standalone_via_help():
    """Copy ONLY the exporter into an empty dir and run --help."""
    tmp = tempfile.mkdtemp()
    try:
        dest = os.path.join(tmp, "mt5_history_export.py")
        shutil.copy(EXPORTER, dest)
        # No run_acquire_data.py / src/ present in tmp -- exactly the Windows PC case.
        assert not os.path.exists(os.path.join(tmp, "run_acquire_data.py"))
        assert not os.path.exists(os.path.join(tmp, "src"))
        r = subprocess.run(
            [sys.executable, dest, "--help"],
            cwd=tmp, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"--help failed: {r.stderr}"
        assert "ModuleNotFoundError" not in r.stderr
        assert "run_acquire_data" not in r.stderr
        assert "usage:" in r.stdout.lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_exporter_has_no_engine_local_imports():
    """Static guard: the source must not import run_acquire_data or src.*."""
    src = open(EXPORTER, encoding="utf-8").read()
    assert "from run_acquire_data" not in src
    assert "import run_acquire_data" not in src
    assert "from src" not in src
    assert "import src" not in src
