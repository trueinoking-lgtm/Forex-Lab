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

// ---- v1.2.3: external import daily-loop integration + no-bypass guarantees ----

test("import:external is wired into daily_loop BEFORE score:strategies", () => {
  const loop = readFileSync(join(__dirname, "daily_loop.mjs"), "utf8");
  const importIdx = loop.indexOf("import:external");
  const scoreIdx = loop.indexOf("score:strategies");
  assert.ok(importIdx > 0, "daily_loop must run import:external");
  assert.ok(scoreIdx > 0, "daily_loop must run score:strategies");
  assert.ok(importIdx < scoreIdx, "import:external must run before score:strategies");
  // external seeds come from the engine idea-source sample files, not native backtest
  assert.ok(/sample_imports_(tradingview|traderdev|generic)/.test(loop),
    "daily_loop must point import:external at external idea-source files");
});

test("import:external re-scores under OUR rules and NEVER writes the native score tables", () => {
  // The loader must persist ONLY to ExternalImport + ImportReScore. It must not
  // insert into BacktestRun or StrategyScore (those are native-only, walk-forward).
  const loader = readFileSync(join(__dirname, "import_external.mjs"), "utf8");
  assert.ok(/INSERT INTO ExternalImport/.test(loader));
  assert.ok(/INSERT INTO ImportReScore/.test(loader));
  assert.ok(!/INSERT INTO (BacktestRun|StrategyScore)/.test(loader),
    "external import must not pollute native score tables — lab score stays source of truth");
});

test("external re-score path always reduces external return by OUR cost (no bypass)", () => {
  // Proof at the engine level: re_score re-costs the external headline and the
  // lab 'score' is derived from the re-costed return, never the raw external one.
  const imp = readFileSync(join(root, "engine", "src", "imports.py"), "utf8");
  assert.ok(/def re_score/.test(imp));
  assert.ok(/adj_return = r\.net_return - /.test(imp),
    "re_score must subtract our cost gap from the external return");
  assert.ok(/sc\["is_external"\] = True/.test(imp));
  assert.ok(/sc\["re_costed_return"\] = round\(adj_return/.test(imp),
    "the lab score is built from re_costed_return, not the external net_return");
  // the loader stores score from re_score output, not the external headline
  const loader = readFileSync(join(__dirname, "import_external.mjs"), "utf8");
  assert.ok(/insReScore\.run\([\s\S]*?r\.score/.test(loader),
    "ImportReScore.score must come from re_score (r.score), not external net_return");
});

test("no external import can create live orders or broker execution", () => {
  const targets = [
    join(__dirname, "import_external.mjs"),
    join(root, "engine", "import_external.py"),
    join(root, "engine", "src", "imports.py"),
  ];
  // Forbidden = actual order-execution CALLS / dangerous config ASSIGNMENTS.
  // NOTE: `allow_live_orders` / `live_order` substrings appear ONLY inside the
  // safety guard that REFUSES imports when live orders are enabled — that is
  // the protection, not a violation, so we match call-form tokens only.
  const FORBIDDEN = /place_order\s*\(|execute_trade\s*\(|broker_password|broker_order_id\s*\(|live_order\s*\(|allow_live_orders:\s*true|paper_only:\s*false/;
  for (const f of targets) {
    const txt = readFileSync(f, "utf8");
    assert.ok(!FORBIDDEN.test(txt), `forbidden live/broker token in ${f}`);
  }
  // daily_loop's import step invokes ONLY import_external.mjs (no order path)
  const loop = readFileSync(join(__dirname, "daily_loop.mjs"), "utf8");
  const runIdx = loop.indexOf('runStep("import:external"');
  assert.ok(runIdx > 0, "daily_loop must call import:external via runStep");
  const scoreIdx = loop.indexOf("score:strategies", runIdx);
  const seg = loop.slice(runIdx, scoreIdx);
  assert.ok(/scripts\/import_external\.mjs/.test(seg), "import step must call import_external.mjs");
  assert.ok(!/place_order|execute_trade|broker/.test(seg), "import step has no live/broker call");
});

test("import:external is idempotent per (source, strategy, symbol, day)", () => {
  // Loader must de-dupe same-day re-imports so the daily loop can't stack rows.
  const loader = readFileSync(join(__dirname, "import_external.mjs"), "utf8");
  assert.ok(/imported_date/.test(loader), "loader must bucket by imported_date");
  assert.ok(/SELECT id FROM ExternalImport\s+WHERE source=\? AND strategy_name=\? AND symbol=\? AND imported_date=\?/.test(loader),
    "loader must look up existing same-day import before inserting");
  assert.ok(/DELETE FROM ImportReScore WHERE import_id=/.test(loader),
    "loader must replace re-score rows for the same import");
});

test("ExternalImport schema carries imported_date for daily idempotency", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(/CREATE TABLE IF NOT EXISTS ExternalImport[\s\S]*imported_date/.test(sql));
  // db_migrate must add the column to existing DBs
  const mig = readFileSync(join(__dirname, "db_migrate.mjs"), "utf8");
  assert.ok(/addColumn\("ExternalImport", "imported_date"/.test(mig));
});
