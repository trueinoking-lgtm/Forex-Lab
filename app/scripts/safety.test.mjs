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

// ---- v1.3: Market Trend Intelligence layer ----

test("v1.3 schema adds MarketTrendSnapshot, TrendPrediction, TrendReviewLesson", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  for (const t of ["MarketTrendSnapshot", "TrendPrediction", "TrendReviewLesson"]) {
    assert.ok(sql.includes(`CREATE TABLE IF NOT EXISTS ${t}`), `missing ${t}`);
  }
});

test("trend prediction REQUIRES an invalidation price (NOT NULL + loader guard)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  // schema-level: invalidation_price is NOT NULL on TrendPrediction
  assert.ok(/CREATE TABLE IF NOT EXISTS TrendPrediction[\s\S]*invalidation_price REAL NOT NULL/.test(sql),
    "TrendPrediction.invalidation_price must be NOT NULL");
  // loader-level: rows without an invalidation are skipped, never trusted
  const loader = readFileSync(join(__dirname, "trend_ingest.mjs"), "utf8");
  assert.ok(/invalidation_price == null/.test(loader),
    "ingest must skip predictions lacking an invalidation price");
});

test("prediction is stored BEFORE outcome (outcome fields nullable, loader omits them)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  // outcome fields exist but are nullable (no NOT NULL) so a prediction is
  // recorded first and reviewed later.
  assert.ok(/TrendPrediction[\s\S]*outcome_price REAL,/.test(sql));
  assert.ok(/TrendPrediction[\s\S]*was_correct INTEGER,/.test(sql));
  const loader = readFileSync(join(__dirname, "trend_ingest.mjs"), "utf8");
  // the INSERT must NOT set outcome_price / was_correct / reviewed_at
  assert.ok(/INSERT INTO TrendPrediction[\s\S]*?VALUES/.test(loader));
  assert.ok(!/INSERT INTO TrendPrediction[\s\S]*?(outcome_price|was_correct|reviewed_at)[\s\S]*?VALUES/.test(loader),
    "ingest must insert predictions without outcome fields (stored before review)");
});

test("outcome review CANNOT overwrite the original prediction fields", () => {
  const review = readFileSync(join(__dirname, "review_trends.mjs"), "utf8");
  // the review UPDATE must touch ONLY outcome/review columns
  const m = review.match(/UPDATE TrendPrediction\s+SET([\s\S]*?)WHERE/);
  assert.ok(m, "review must UPDATE TrendPrediction");
  const setClause = m[1];
  for (const col of ["outcome_price", "outcome_direction", "was_correct", "reviewed_at"]) {
    assert.ok(setClause.includes(col), `review should set ${col}`);
  }
  for (const forbidden of ["predicted_direction", "confidence_score", "invalidation_price",
    "prediction_time", "entry_context_json", "horizon", "symbol"]) {
    assert.ok(!setClause.includes(forbidden),
      `review must NOT overwrite original prediction field ${forbidden}`);
  }
});

test("review loop compares against three naive baselines", () => {
  const review = readFileSync(join(__dirname, "review_trends.mjs"), "utf8");
  assert.ok(/prevCandle/.test(review), "baseline (a) follow previous candle");
  assert.ok(/noChange/.test(review), "baseline (b) assume no change");
  assert.ok(/emaTrend/.test(review), "baseline (c) follow EMA trend");
  assert.ok(/TrendReviewLesson/.test(review), "misses must be stored as lessons");
});

test("uncertain label is allowed AND encouraged (vocab present in schema + page)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(/regime TEXT NOT NULL,\s*--\s*trend \| range \| volatile \| uncertain/.test(sql),
    "regime vocab must include uncertain");
  const page = readFileSync(join(__dirname, "..", "app", "market-trends", "page.tsx"), "utf8");
  assert.ok(/uncertain/.test(page), "trends page must surface the uncertain label");
});

test("NO certainty language in trend UI or scripts", () => {
  const certainty = /\b(guaranteed|risk[- ]free|100%\s+(sure|certain)|will\s+(rise|fall|reach)|sure\s+thing)\b/i;
  const files = [
    join(__dirname, "..", "app", "market-trends", "page.tsx"),
    join(__dirname, "trend_ingest.mjs"),
    join(__dirname, "review_trends.mjs"),
  ];
  for (const f of files) {
    const txt = readFileSync(f, "utf8");
    assert.ok(!certainty.test(txt), `certainty language found in ${f}`);
  }
});

test("trend intelligence performs NO live execution (no order/broker code)", () => {
  const files = [
    join(__dirname, "trend_ingest.mjs"),
    join(__dirname, "review_trends.mjs"),
    join(root, "engine", "run_trends.py"),
    join(root, "engine", "src", "trend.py"),
  ];
  for (const f of files) {
    const txt = readFileSync(f, "utf8");
    assert.ok(!/place_order|execute_trade|broker_password|create_order|submit_order|position_size/.test(txt),
      `forbidden execution token in ${f}`);
  }
});

test("trend engine refuses to run if live orders are enabled", () => {
  const rt = readFileSync(join(root, "engine", "run_trends.py"), "utf8");
  assert.ok(/paper_only/.test(rt) && /allow_live_orders/.test(rt));
  assert.ok(/Refusing/.test(rt), "run_trends must refuse when paper_only false / live allowed");
});

test("demo execution: schema hard-locks broker_mode to demo (no live)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  assert.ok(/CREATE TABLE IF NOT EXISTS DemoExecutionOrder[\s\S]*?CHECK \(broker_mode = 'demo'\)/.test(sql),
    "DemoExecutionOrder must CHECK broker_mode='demo'");
  assert.ok(/CREATE TABLE IF NOT EXISTS ExecutionControl[\s\S]*?CHECK \(broker_mode = 'demo'\)/.test(sql),
    "ExecutionControl must CHECK broker_mode='demo'");
});

test("demo execution: stop_loss and take_profit are NOT NULL (required)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  const block = sql.slice(sql.indexOf("CREATE TABLE IF NOT EXISTS DemoExecutionOrder"));
  assert.ok(/stop_loss REAL NOT NULL/.test(block), "stop_loss required");
  assert.ok(/take_profit REAL NOT NULL/.test(block), "take_profit required");
});

test("demo execution: secrets are never stored (no secret columns, redacted raw)", () => {
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  const block = sql.slice(sql.indexOf("CREATE TABLE IF NOT EXISTS DemoExecutionOrder"),
                          sql.indexOf("CREATE TABLE IF NOT EXISTS ExecutionJournal"));
  assert.ok(!/password|secret|api_key|token/.test(block),
    "DemoExecutionOrder must not store broker secrets");
  assert.ok(/raw_response_redacted_json/.test(block), "only redacted raw stored");
});

test("demo execution: guards reject live mode, missing SL/TP, missing risk, no paper signal", () => {
  const g = readFileSync(join(root, "engine", "src", "execution", "guards.py"), "utf8");
  assert.ok(/broker_mode != "demo"/.test(g), "live mode rejected");
  assert.ok(/allow_live_orders/.test(g) && /demo-only bridge refuses/.test(g), "ALLOW_LIVE_ORDERS enforced");
  assert.ok(/missing stop_loss/.test(g), "missing SL rejected");
  assert.ok(/missing take_profit/.test(g), "missing TP rejected");
  assert.ok(/risk_check/.test(g), "deterministic risk engine required");
  assert.ok(/no parent paper Signal/.test(g), "paper signal required");
  assert.ok(/open demo trades .* cap/.test(g), "max open demo trades enforced");
  assert.ok(/kill switch/.test(g), "kill switch enforced");
});

test("demo execution: mock adapter is the default and always works", () => {
  const f = readFileSync(join(root, "engine", "src", "execution", "factory.py"), "utf8");
  assert.ok(/name = \(name or "mock"\)/.test(f) || /default 'mock'/.test(f), "mock is the default");
  assert.ok(/deriv_mt5/.test(f) && /oanda_practice/.test(f), "real adapters selectable by name");
  const mock = readFileSync(join(root, "engine", "src", "execution", "mock_adapter.py"), "utf8");
  assert.ok(/class MockDemoAdapter/.test(mock), "mock adapter present");
});

test("demo execution: real adapters fail loud without credentials", () => {
  const deriv = readFileSync(join(root, "engine", "src", "execution", "deriv_mt5.py"), "utf8");
  const oanda = readFileSync(join(root, "engine", "src", "execution", "oanda_practice.py"), "utf8");
  assert.ok(/RuntimeError[\s\S]*?credentials missing/.test(deriv), "deriv fails without creds");
  assert.ok(/RuntimeError[\s\S]*?credentials missing/.test(oanda), "oanda fails without creds");
  assert.ok(/api-fxpractice\.oanda\.com/.test(oanda), "oanda targets practice host only");
});

test("demo execution: CLI refuses when allow_live_orders is true", () => {
  const cli = readFileSync(join(root, "engine", "run_execution.py"), "utf8");
  assert.ok(/ALLOW_LIVE_ORDERS=true/.test(cli), "run_execution checks ALLOW_LIVE_ORDERS");
  assert.ok(/kill switch engaged/.test(cli), "run_execution honours kill switch");
  assert.ok(/broker_mode != 'demo'/.test(cli), "run_execution checks broker_mode");
});

test("demo execution: npm scripts wired for check/order/update/journal/kill-switch", () => {
  const pkg = readFileSync(join(__dirname, "..", "package.json"), "utf8");
  for (const s of ["execution:check", "execution:demo-order", "execution:update",
                   "execution:journal", "execution:kill-switch"]) {
    assert.ok(pkg.includes(`"${s}"`), `missing npm script ${s}`);
  }
});

test("demo execution: page surfaces broker mode + kill switch status", () => {
  const page = readFileSync(join(__dirname, "..", "app", "demo-execution", "page.tsx"), "utf8");
  assert.ok(/broker_mode/.test(page), "page shows broker mode");
  assert.ok(/kill switch/i.test(page), "page shows kill switch status");
  assert.ok(/open demo/i.test(page), "page shows open positions");
  assert.ok(/rejected/i.test(page), "page shows rejected orders");
  assert.ok(/spread/i.test(page), "page shows spread-at-entry");
  assert.ok(/paper vs demo/i.test(page), "page shows paper vs demo PnL");
});

test("demo execution: lifecycle is deterministic and rerun-safe per run_id", () => {
  const cli = readFileSync(join(root, "engine", "run_execution.py"), "utf8");
  assert.ok(/run_id = args.run_id or/.test(cli), "run_id must be stable per run");
  assert.ok(/already completed/.test(cli) && /skipped/.test(cli),
    "same run_id must skip instead of duplicating proof rows");
  assert.ok(/uuid/.test(cli), "new run_id generated when not supplied");
});

test("demo execution: mock lifecycle writes journal with paper+demo PnL, spread, slippage, latency", () => {
  const cli = readFileSync(join(root, "engine", "run_execution.py"), "utf8");
  assert.ok(/expected_paper_pnl/.test(cli) && /actual_demo_pnl/.test(cli),
    "journal row must record expected + actual pnl");
  assert.ok(/slippage/.test(cli) && /spread/.test(cli) && /latency_ms/.test(cli),
    "journal must record slippage, spread, latency");
  assert.ok(/build_adapter\("mock"/.test(cli), "lifecycle must use the mock adapter");
  assert.ok(/broker_mode[=:]['"]demo['"]/.test(cli), "lifecycle must be labelled demo");
  assert.ok(/not a real broker execution/.test(cli), "must label as simulated");
});

test("demo execution: close before final PnL journal is required", () => {
  const cli = readFileSync(join(root, "engine", "run_execution.py"), "utf8");
  assert.ok(/close_demo_order/.test(cli), "lifecycle must close the order before journaling");
  assert.ok(/actual_demo_pnl IS NOT NULL/.test(cli), "journal requires a filled/closed pnl");
});

test("demo execution: paper PnL cannot be overwritten by broker response", () => {
  const cli = readFileSync(join(root, "engine", "run_execution.py"), "utf8");
  assert.ok(/expected_paper_pnl = round\(\(exit_price - signal\.entry\)/.test(cli),
    "paper PnL computed from paper signal, not the fill");
});

test("demo execution: kill switch blocks lifecycle execution", () => {
  const cli = readFileSync(join(root, "engine", "run_execution.py"), "utf8");
  assert.ok(/kill switch engaged — lifecycle blocked/.test(cli),
    "mock-lifecycle must refuse when kill_switch is set");
});

test("demo execution: no secrets in journal or raw response", () => {
  const cli = readFileSync(join(root, "engine", "run_execution.py"), "utf8");
  assert.ok(/raw_redacted/.test(cli), "only redacted raw stored on order");
  assert.ok(/lesson_json/.test(cli) && /note.*mock/.test(cli), "lesson_json stored, no secrets");
  const sql = readFileSync(join(__dirname, "..", "schema.sql"), "utf8");
  const jblock = sql.slice(sql.indexOf("CREATE TABLE IF NOT EXISTS ExecutionJournal"),
                           sql.indexOf("CREATE TABLE IF NOT EXISTS ExecutionControl"));
  assert.ok(!/password|secret|api_key|token/.test(jblock),
    "ExecutionJournal must not store broker secrets");
});

test("demo execution: daily report separates mock execution quality from real broker demo", () => {
  const rep = readFileSync(join(__dirname, "report_daily.mjs"), "utf8");
  assert.ok(/Demo execution quality/.test(rep), "report has execution quality block");
  assert.ok(/MOCK \(simulated, not a real venue\)/.test(rep), "mock clearly separated from real");
  assert.ok(/REAL DEMO BROKER/.test(rep), "real demo broker labelled separately");
  assert.ok(/kill-switch/.test(rep) || /kill switch/.test(rep), "report shows kill switch status");
  assert.ok(/worst_slip/.test(rep), "report shows worst slippage");
  assert.ok(/paper-vs-demo/.test(rep) || /mismatch/.test(rep), "report shows paper-vs-demo mismatch");
});

test("trends are wired into the daily loop AFTER scoring, review after outcomes", () => {
  const loop = readFileSync(join(__dirname, "daily_loop.mjs"), "utf8");
  const scoreIdx = loop.indexOf("score:strategies");
  const detectIdx = loop.indexOf("trends:detect");
  const ingestIdx = loop.indexOf("trends:ingest");
  const reviewIdx = loop.indexOf("review:trends");
  assert.ok(detectIdx > scoreIdx, "trends:detect runs after score:strategies (needs fresh history)");
  assert.ok(ingestIdx > detectIdx, "trends:ingest runs after detect");
  assert.ok(reviewIdx > ingestIdx, "review:trends runs after ingest");
});
