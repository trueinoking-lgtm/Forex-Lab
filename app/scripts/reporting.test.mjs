import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import Database from "better-sqlite3";

test("canonical payload exposes accounting-v2 and separates advisory from evidence", () => {
  const root = join(import.meta.dirname, "..", "..");
  const temp = mkdtempSync(join(tmpdir(), "aether-reporting-"));
  try {
    const dbPath = join(temp, "forex_lab.db");
    const results = join(temp, "results");
    mkdirSync(results);
    const db = new Database(dbPath);
    db.exec(readFileSync(join(root, "app", "schema.sql"), "utf8"));
    db.prepare(`INSERT INTO Strategy(name) VALUES ('family_a')`).run();
    const run = db.prepare(`INSERT INTO BacktestRun
      (strategy,pair,timeframe,generated_at,oos_return,bh_oos_return,beats_bh)
      VALUES ('family_a','EURUSD=X','1d','2026-07-21',0.01,0.02,0)`).run();
    db.prepare(`INSERT INTO StrategyScore(run_id,strategy,pair,score,robustness)
      VALUES (?,'family_a','EURUSD=X',31,0.1)`).run(run.lastInsertRowid);
    db.prepare(`INSERT INTO PaperLedgerSnapshot
      (ts,starting_equity,current_equity,realized_pnl,unrealized_pnl,open_risk,
       max_concurrent_risk,bankrupt,accounting_version,accounting_model,
       ledger_updated_at,ignored_legacy_records,ignored_legacy_note)
      VALUES ('2026-07-21',10000,10025,20,5,100,2,0,2,
       'normalized_equal_risk_v1','2026-07-21T00:00:00Z',3,'legacy excluded')`).run();
    db.close();
    writeFileSync(join(results, "watcher_last_result.json"), JSON.stringify({ tradeable: false, regime: "range", adx: 18, close: 1.17 }));
    writeFileSync(join(results, "backtest_EURUSD=X.json"), JSON.stringify({
      source: "yfinance", timeframe: "1d", results: [{ strategy: "family_a", rejection_reasons: ["score below gate"] }],
    }));
    execFileSync("node", [join(root, "app", "scripts", "report_payload.mjs")], {
      cwd: join(root, "app"), env: { ...process.env, FOREX_LAB_DB: dbPath, AETHER_RESULTS_DIR: results },
    });
    const message = readFileSync(join(results, "daily_report_message.md"), "utf8");
    for (const field of ["starting equity", "current equity", "realized PnL", "unrealized PnL",
      "open risk", "maximum concurrent risk", "bankrupt", "accounting version",
      "last ledger update", "ignored legacy records"]) assert.match(message, new RegExp(field, "i"));
    assert.match(message, /accounting_model=normalized_equal_risk_v1/);
    assert.match(message, /pnl_unit=account_currency_USD/);
    assert.ok(message.indexOf("Advisory (market regime, not a signal)") < message.indexOf("Strategy evidence"));
    assert.match(message, /watcher-eligible strategies: 0/);
    const payload = JSON.parse(readFileSync(join(results, "daily_report_payload.json"), "utf8"));
    assert.equal(payload.paper.accounting_version, 2);
    assert.equal(payload.paper.current_equity, 10025);
    assert.equal(payload.watcher_eligible, 0);
  } finally { rmSync(temp, { recursive: true, force: true }); }
});
