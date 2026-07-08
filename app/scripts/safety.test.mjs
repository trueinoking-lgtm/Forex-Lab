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

// ---- v1.2.1 integrity hardening ----
test("score_strategies normalizes yfinance =X pair to canonical Market symbol", () => {
  const src = readFileSync(join(__dirname, "score_strategies.mjs"), "utf8");
  assert.ok(/canonicalPair/.test(src), "expected canonicalPair() normalizer");
  assert.ok(/=X\$/.test(src) && /=C\$/.test(src), "normalizer must strip =X and =C suffixes");
  const seed = readFileSync(join(__dirname, "seed_markets.mjs"), "utf8");
  assert.ok(/symbol: "EURUSD"/.test(seed), "Market seed stores canonical EURUSD (no =X)");
});

test("BacktestRun is deduped per (strategy, pair, run_date) — no accumulation on re-run", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(/UNIQUE\(strategy, pair, run_date\)/.test(sql), "needs unique constraint on run");
  const src = readFileSync(join(__dirname, "score_strategies.mjs"), "utf8");
  assert.ok(/ON CONFLICT\(strategy,pair,run_date\) DO UPDATE SET/.test(src), "loader must upsert");
});

test("paper PnL is account-scaled via units (not per-unit move added to equity)", () => {
  const src = readFileSync(join(__dirname, "paper_update_pnl.mjs"), "utf8");
  assert.ok(/units/.test(src), "must use risk-sized units");
  assert.ok(/account0 \+ realized \+ openPnl|account0 \+ realized/.test(src), "equity must be account0 + realized + open");
  assert.ok(!/\bequity \+= pnl;\s*\n/.test(src), "old per-unit equity+=pnl must be gone");
  // open risk must be >= 0 (abs), not sign-affected
  assert.ok(/Math\.abs\(t\.entry - t\.stop_loss\) \* units/.test(src), "open_risk uses abs distance");
});

test("OutcomeReview is deduped per (trade, horizon, day)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(/UNIQUE\(paper_trade_id, horizon, review_date\)/.test(sql));
  const src = readFileSync(join(__dirname, "review_outcomes.mjs"), "utf8");
  assert.ok(/ON CONFLICT\(paper_trade_id, horizon, review_date\) DO UPDATE SET/.test(src));
});

test("Signal/PaperTrade carry units column (account-scaled PnL)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(/CREATE TABLE IF NOT EXISTS Signal[\s\S]*units REAL/.test(sql));
  assert.ok(/CREATE TABLE IF NOT EXISTS PaperTrade[\s\S]*units REAL/.test(sql));
});

test("Signal is idempotent per (pair, strategy, generated_at) — no signal dupes", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(/CREATE TABLE IF NOT EXISTS Signal[\s\S]*UNIQUE\(pair, strategy, generated_at\)/.test(sql));
});

test("cross-market matrix ranks native + external by lab score with robustness tiebreak", () => {
  const src = readFileSync(join(__dirname, "..", "lib", "db.ts"), "utf8");
  assert.ok(/UNION ALL/.test(src), "matrix must combine native + external rows");
  assert.ok(/robustness desc/.test(src), "must use robustness tiebreak");
  assert.ok(/is_external=1|1 AS is_external/.test(src), "external rows tagged is_external");
});
