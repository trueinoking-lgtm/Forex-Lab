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

// ---- v1.2 multi-market research hub ----
test("v1.2 schema adds Market, ExternalImport, ImportReScore + run flags", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  for (const t of ["Market", "ExternalImport", "ImportReScore"]) {
    assert.ok(sql.includes(`CREATE TABLE IF NOT EXISTS ${t}`), `missing ${t}`);
  }
  assert.ok(/asset_class TEXT DEFAULT 'forex'/.test(sql));
  assert.ok(/is_external INTEGER NOT NULL DEFAULT 0/.test(sql));
  assert.ok(/ExternalImport[\s\S]*is_external INTEGER NOT NULL DEFAULT 1/.test(sql));
});

test("crypto research mode is disabled by default in seed", () => {
  const seed = readFileSync(join(__dirname, "seed_markets.mjs"), "utf8");
  assert.ok(/BTCUSD[\s\S]*enabled: 0/.test(seed) || /symbol: "BTCUSD"[\s\S]*?enabled: 0/.test(seed));
  assert.ok(/ETHUSD[\s\S]*enabled: 0/.test(seed) || /symbol: "ETHUSD"[\s\S]*?enabled: 0/.test(seed));
});

test("import_external.mjs performs no live execution (no order/execute/broker code)", () => {
  const src = readFileSync(join(__dirname, "import_external.mjs"), "utf8");
  assert.ok(!/place_order|execute_trade|broker_password|live_order|api_key|secret/.test(src));
});

test("engine re-scores external imports with OUR cost model (source-of-truth)", () => {
  // The re_score path must reduce an external no-cost return by our spread/slippage.
  const imp = readFileSync(join(root, "engine", "src", "imports.py"), "utf8");
  assert.ok(/def re_score/.test(imp));
  assert.ok(/our_total_bps|our_cost_bps|cost_gap_bps/.test(imp));
  assert.ok(/validate_import/.test(imp)); // fail-loud on fake data
  assert.ok(/_MAX_ABS_RETURN/.test(imp)); // rejects impossible returns
});

test("external import labeling: re-scored rows are always is_external=1", () => {
  const imp = readFileSync(join(root, "engine", "src", "imports.py"), "utf8");
  assert.ok(/"is_external": True/.test(imp) || /sc\["is_external"\] = True/.test(imp));
  const loader = readFileSync(join(__dirname, "import_external.mjs"), "utf8");
  assert.ok(/is_external[\s\S]*?,1\)/.test(loader)); // ExternalImport.is_external=1 on insert
});

test("market universe source file defines metadata fields", () => {
  const mk = readFileSync(join(root, "engine", "src", "markets.py"), "utf8");
  for (const f of ["asset_class", "symbol", "session", "spread_model", "volatility_profile", "data_source"]) {
    assert.ok(mk.includes(f), `markets.py missing ${f}`);
  }
  assert.ok(/UNIVERSE/.test(mk));
});
