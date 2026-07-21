import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import Database from "better-sqlite3";

const CANONICAL_SHA = "4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2";
const requiredLines = [
  "Report class: short_window_yfinance_advisory",
  "Watcher eligible strategies: 0",
  "Canonical research source: MT5 D1",
  "Advisory source: yfinance D1",
  "Sources differ: YES",
  "All researched families: REJECTED",
  "No signal created",
  "No order placed",
];

test("generated report has hardened canonical/advisory source policy", () => {
  const root = join(import.meta.dirname, "..", "..");
  const temp = mkdtempSync(join(tmpdir(), "aether-source-policy-"));
  try {
    const dbPath = join(temp, "forex_lab.db");
    const results = join(temp, "results");
    mkdirSync(results);
    const db = new Database(dbPath);
    db.exec(readFileSync(join(root, "app", "schema.sql"), "utf8"));
    db.close();
    execFileSync("node", ["scripts/report_payload.mjs"], {
      cwd: join(root, "app"),
      env: { ...process.env, FOREX_LAB_DB: dbPath, AETHER_RESULTS_DIR: results },
    });
    const payload = JSON.parse(readFileSync(join(results, "daily_report_payload.json"), "utf8"));
    assert.equal(payload.report_class, "short_window_yfinance_advisory");
    assert.equal(payload.source_policy.advisory.provider, "yfinance");
    assert.equal(payload.source_policy.canonical.provider, "MT5");
    assert.equal(payload.source_policy.sources_differ, "YES");
    assert.equal(payload.canonical_research_fingerprint, CANONICAL_SHA);
    assert.equal(payload.watcher_eligible, 0);
    for (const line of requiredLines) assert.ok(payload.message.includes(line), line);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});
