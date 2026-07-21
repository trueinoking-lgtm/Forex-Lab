import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

import pytest

from src.accounting import ACCOUNTING_MODEL_VERSION, accounting_metadata

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"starting_equity", "current_equity", "realized_pnl", "unrealized_pnl",
            "open_risk", "max_concurrent_risk", "bankrupt", "accounting_version",
            "ignored_legacy_records", "ledger_updated_at"}


def build_ledger(closed_v2_pnl):
    with tempfile.TemporaryDirectory(prefix="aether-ledger-") as td:
        db_path = Path(td) / "forex_lab.db"
        results = Path(td) / "results"
        results.mkdir()
        con = sqlite3.connect(db_path)
        con.executescript((ROOT / "app/schema.sql").read_text())
        base = ("EURUSD=X", "family", 1, 1.1, 1.0, 1.2, 1, "2026-07-21")
        con.execute("""INSERT INTO PaperTrade
          (pair,strategy,direction,entry,stop_loss,take_profit,units,opened_at,status,pnl,accounting_version)
          VALUES (?,?,?,?,?,?,?,?, 'closed', ?,2)""", (*base, closed_v2_pnl))
        con.execute("""INSERT INTO PaperTrade
          (pair,strategy,direction,entry,stop_loss,take_profit,units,opened_at,status,pnl,accounting_version)
          VALUES (?,?,?,?,?,?,?,?, 'closed', 999999,NULL)""", base)
        con.execute("INSERT INTO PnlSnapshot(ts,equity,accounting_version) VALUES ('legacy',999999,NULL)")
        con.commit()
        con.close()
        env = {**os.environ, "FOREX_LAB_DB": str(db_path), "AETHER_RESULTS_DIR": str(results)}
        subprocess.run(["node", str(ROOT / "app/scripts/paper_update_pnl.mjs")],
                       cwd=ROOT / "app", env=env, check=True, capture_output=True, text=True)
        subprocess.run(["node", str(ROOT / "app/scripts/report_payload.mjs")],
                       cwd=ROOT / "app", env=env, check=True, capture_output=True, text=True)
        return json.loads((results / "daily_report_payload.json").read_text())


def test_v2_payload_keys_and_metadata():
    payload = build_ledger(25)
    assert REQUIRED <= payload["paper"].keys()
    assert payload["paper"]["accounting_version"] == ACCOUNTING_MODEL_VERSION
    assert accounting_metadata(has_explicit_stop=True)["accounting_model"] == "normalized_equal_risk_v1"


def test_legacy_rows_excluded_and_counted():
    paper = build_ledger(25)["paper"]
    assert paper["current_equity"] == 10025
    assert paper["ignored_legacy_records"] == 2


@pytest.mark.parametrize(("pnl", "bankrupt"), [(1, False), (-10000, True), (-10001, True)])
def test_bankruptcy_boundary(pnl, bankrupt):
    assert build_ledger(pnl)["paper"]["bankrupt"] is bankrupt


def test_report_import_safety():
    source = (ROOT / "app/scripts/report_payload.mjs").read_text()
    imports = "\n".join(line for line in source.splitlines() if line.lstrip().startswith("import "))
    for forbidden in ("run_execution", "remote_mt5", "place_order", "order"):
        assert forbidden not in imports
