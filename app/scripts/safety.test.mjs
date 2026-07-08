// scripts/safety.test.mjs — TS/JS layer safety tests (node --test).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { redact } from "./db.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..", "..");

test("engine config forbids live orders", () => {
  const cfg = readFileSync(join(root, "engine", "config.yaml"), "utf8");
  assert.match(cfg, /paper_only:\s*true/);
  assert.match(cfg, /allow_live_orders:\s*false/);
});

test("no broker secrets or order-execution code in engine", () => {
  const src = join(root, "engine", "src");
  for (const f of readdirSync(src)) {
    if (!f.endsWith(".py")) continue;
    const txt = readFileSync(join(src, f), "utf8");
    assert.ok(!/place_order|execute_trade|broker_password/.test(txt));
  }
});

test("all DB schema tables present", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  for (const t of ["PriceCandle", "Strategy", "BacktestRun", "StrategyScore",
    "Signal", "DecisionJournal", "PaperTrade", "PnlSnapshot", "OutcomeReview",
    "RuleSet", "RuleChange", "DailyReport"]) {
    assert.ok(sql.includes(`CREATE TABLE IF NOT EXISTS ${t}`), `missing ${t}`);
  }
});

test("no live-order columns in schema (paper-only by design)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(!/live_order|broker_order_id/.test(sql));
});

test("secrets are redacted by logger", () => {
  assert.equal(redact("api_key=abcdefgh12345678"), "api_key=[REDACTED]");
  assert.equal(redact("plain text"), "plain text");
});

test("scheduler has a run-log + lock table (auditability + no overlap)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(sql.includes("CREATE TABLE IF NOT EXISTS SchedulerRunLog"));
  assert.ok(sql.includes("CREATE TABLE IF NOT EXISTS SchedulerLock"));
});

test("daily_loop refuses to run while a lock is held", async () => {
  const Database = (await import("better-sqlite3")).default;
  const { execFileSync } = await import("node:child_process");
  const dbPath = join(__dirname, "..", "forex_lab.db");
  const appDir = join(__dirname, "..");
  const db = new Database(dbPath);
  db.prepare("INSERT OR REPLACE INTO SchedulerLock (id,locked_at,owner) VALUES (1,?,?)")
    .run(new Date().toISOString(), "test-hold:1");
  db.close();
  let refused = false;
  try {
    execFileSync("node", [join(appDir, "scripts", "daily_loop.mjs")], { cwd: appDir, stdio: "pipe" });
  } catch (e) {
    const out = (e.stdout?.toString() || "") + (e.stderr?.toString() || "");
    refused = /Refusing overlapping run/.test(out);
  }
  // release lock so other tests aren't affected
  const db2 = new Database(dbPath);
  db2.prepare("DELETE FROM SchedulerLock WHERE id=1").run();
  db2.close();
  assert.ok(refused, "expected daily_loop to refuse while lock held");
});

test("engine config still forbids live + regime enum wired", () => {
  const cfg = readFileSync(join(root, "engine", "config.yaml"), "utf8");
  assert.match(cfg, /paper_only:\s*true/);
  assert.match(cfg, /allow_live_orders:\s*false/);
  // signals.py must define an explicit regime enum + validator
  const sig = readFileSync(join(root, "engine", "src", "signals.py"), "utf8");
  assert.ok(/REGIMES\s*=\s*\(/.test(sig));
  assert.ok(/def validate_regime/.test(sig));
});
