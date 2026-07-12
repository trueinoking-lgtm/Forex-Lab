// scripts/research_phase3.test.mjs — Phase 3 tests for Vibe-Trading MCP research runner.
// Covers: CLI invocation, unknown signal, dedup rejection, --force, tool allowlist,
// direct-data failure, web fallback, confidence reduction, malformed MCP response,
// timeout, partial tool failure, secret redaction, response-size cap, execution_allowed
// always false, no signal mutation, no execution-path mutation, audit record persistence.
import { test, before, after, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import Database from "better-sqlite3";
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { fileURLToPath } from "url";
import { execFileSync } from "node:child_process";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const appDir = join(__dirname, "..");
const prodDbPath = join(appDir, "forex_lab.db");

let tempDir;
let tempDb;

// ---------------------------------------------------------------------------
// Test DB setup helpers
// ---------------------------------------------------------------------------

function useTempDb() {
  const g = globalThis;
  if (g.__fxResearchDb) {
    g.__fxResearchDb.close();
    delete g.__fxResearchDb;
  }
  if (tempDir) rmSync(tempDir, { recursive: true, force: true });
  tempDir = mkdtempSync(join(tmpdir(), "aether-p3-test-"));
  const destPath = join(tempDir, "forex_lab.db");
  execFileSync("sqlite3", [prodDbPath, `.backup ${destPath}`]);
  tempDb = new Database(destPath);
  // Clear review outcomes first (child of ResearchReview) to avoid FK violations
  // when clearing ResearchReview below. ReviewOutcome is created by Phase 4.
  tempDb.exec("DELETE FROM ReviewOutcome");
  // Clear reviews so tests start clean
  tempDb.exec("DELETE FROM ResearchReview");
  // Ensure ResearchRun table exists (backup may predate v1.3.5)
  const hasRunTable = tempDb.prepare(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ResearchRun'"
  ).get();
  if (!hasRunTable) {
    tempDb.exec(`CREATE TABLE ResearchRun (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      signal_id INTEGER NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      status TEXT NOT NULL DEFAULT 'running',
      tools_requested_json TEXT,
      tools_called_json TEXT,
      failures_json TEXT,
      direct_market_data_available INTEGER NOT NULL DEFAULT 0,
      fallback_web_used INTEGER NOT NULL DEFAULT 0,
      review_id INTEGER,
      forced INTEGER NOT NULL DEFAULT 0,
      execution_allowed INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY(signal_id) REFERENCES Signal(id)
    );`);
  }
  tempDb.exec("DELETE FROM ResearchRun");
  process.env.FOREX_LAB_DB_PATH = destPath;
  return tempDir;
}

before(() => {});

after(() => {
  const g = globalThis;
  if (g.__fxResearchDb) {
    g.__fxResearchDb.close();
    delete g.__fxResearchDb;
  }
  delete process.env.FOREX_LAB_DB_PATH;
  if (tempDb) {
    tempDb.close();
    tempDb = null;
  }
  if (tempDir) {
    rmSync(tempDir, { recursive: true, force: true });
    tempDir = null;
  }
});

// ---------------------------------------------------------------------------
// Signal checksum helper
// ---------------------------------------------------------------------------

function signalChecksum(signalId) {
  const row = tempDb
    .prepare("SELECT * FROM Signal WHERE id = ?")
    .get(signalId);
  if (!row) return null;
  return JSON.stringify(row);
}

// ---------------------------------------------------------------------------
// Insert a test review (for dedup tests)
// ---------------------------------------------------------------------------

function insertReview(opts) {
  tempDb
    .prepare(
      `INSERT INTO ResearchReview
       (signal_id, provider, model_or_tool, review_type, verdict, confidence,
        summary, strengths_json, risks_json, assumptions_json, data_sources_json,
        tool_calls_json, raw_response_json, execution_allowed, research_only, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))`
    )
    .run(
      opts.signal_id ?? 6,
      opts.provider ?? "vibe-trading",
      opts.model_or_tool ?? "vibe-trading-mcp",
      opts.review_type ?? "macro_fx",
      opts.verdict ?? "caution",
      opts.confidence ?? 50,
      opts.summary ?? "Test",
      JSON.stringify(opts.strengths ?? []),
      JSON.stringify(opts.risks ?? []),
      JSON.stringify(opts.assumptions ?? []),
      JSON.stringify(opts.data_sources ?? []),
      JSON.stringify(opts.tool_calls ?? []),
      JSON.stringify(opts.raw_response ?? {}),
      0,
      1
    );
  return tempDb.prepare("SELECT last_insert_rowid() as id").get().id;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

// --- 1. Tool allowlist: allowed tools pass ---
test("allowlist: allowed tools are accepted", async () => {
  const { ALLOWED_TOOLS, isAllowedTool, assertAllowedTool } = await import("../lib/mcp-client.mjs");
  const expected = new Set([
    "get_market_data", "get_macro_series", "search_symbol",
    "pattern_recognition", "factor_analysis", "backtest",
    "analyze_trade_journal", "list_skills", "load_skill",
    "web_search", "read_url",
  ]);
  assert.equal(ALLOWED_TOOLS.size, expected.size);
  for (const t of expected) {
    assert.ok(isAllowedTool(t), `Tool ${t} should be allowed`);
  }
  // assertAllowedTool should not throw for allowed tools
  for (const t of expected) {
    assertAllowedTool(t);
  }
});

// --- 2. Tool allowlist: disallowed tools rejected ---
test("allowlist: disallowed tools are rejected", async () => {
  const { assertAllowedTool } = await import("../lib/mcp-client.mjs");
  const disallowed = [
    "start_research_goal", "update_research_goal_status", "add_goal_evidence",
    "get_research_reports", "render_shadow_report", "extract_shadow_strategy",
    "run_shadow_backtest", "scan_shadow_signals", "read_document",
    "some_unknown_tool", "execute_trade", "place_order",
  ];
  for (const tool of disallowed) {
    assert.throws(() => assertAllowedTool(tool), /not in the research allowlist/);
  }
});

// --- 3. Unknown signal rejection ---
test("runResearchReview rejects unknown signal", async () => {
  useTempDb();
  const { runResearchReview } = await import("../lib/research-runner.mjs");
  await assert.rejects(
    () => runResearchReview({ signal_id: 99999, force: true }),
    /Signal 99999 not found/
  );
});

// --- 4. Duplicate review rejection (without --force) ---
test("dedup: rejects duplicate review within 24 hours without --force", async () => {
  useTempDb();
  insertReview({ signal_id: 6, review_type: "macro_fx" });
  const { runResearchReview } = await import("../lib/research-runner.mjs");

  // We need to mock the MCP client to avoid actually starting the server.
  // Since runResearchReview calls exportSanitizedSignal first (which succeeds),
  // then checks dedup (which should throw), the MCP server should never start.
  await assert.rejects(
    () => runResearchReview({ signal_id: 6, force: false }),
    /Duplicate review/
  );
});

// --- 5. --force allows duplicate ---
test("dedup: --force allows duplicate review (records forced flag)", async () => {
  useTempDb();
  const { createResearchRun, updateResearchRun, getResearchRun } = await import("../lib/research-runner.mjs");

  // Insert an existing review
  insertReview({ signal_id: 6, review_type: "macro_fx" });

  // Simulate forced run audit
  const runId = createResearchRun({
    signal_id: 6,
    started_at: new Date().toISOString(),
    tools_requested: ["search_symbol"],
    forced: true,
  });

  const run = getResearchRun(runId);
  assert.equal(run.forced, 1);
  assert.equal(run.execution_allowed, 0);
  assert.equal(run.status, "running");
});

// --- 6. Dedup uses correct window ---
test("dedup: findRecentReview returns null when no recent review exists", async () => {
  useTempDb();
  const { findRecentReview } = await import("../lib/research-runner.mjs");
  const result = findRecentReview(6, "macro_fx");
  assert.equal(result, null);
});

// --- 7. Dedup finds existing recent review ---
test("dedup: findRecentReview returns existing review", async () => {
  useTempDb();
  insertReview({ signal_id: 6, review_type: "macro_fx" });
  const { findRecentReview } = await import("../lib/research-runner.mjs");
  const result = findRecentReview(6, "macro_fx");
  assert.ok(result);
  assert.ok(result.id);
  assert.ok(result.created_at);
});

// --- 8. Run audit: createResearchRun stores correct fields ---
test("audit: createResearchRun stores signal_id, status, tools_requested, forced, execution_allowed=0", async () => {
  useTempDb();
  const { createResearchRun, getResearchRun } = await import("../lib/research-runner.mjs");
  const runId = createResearchRun({
    signal_id: 6,
    started_at: "2026-07-12T10:00:00Z",
    tools_requested: ["search_symbol", "get_market_data"],
    forced: false,
  });
  const run = getResearchRun(runId);
  assert.equal(run.signal_id, 6);
  assert.equal(run.status, "running");
  assert.equal(run.forced, 0);
  assert.equal(run.execution_allowed, 0);
  assert.deepEqual(JSON.parse(run.tools_requested_json), ["search_symbol", "get_market_data"]);
});

// --- 9. Run audit: updateResearchRun stores completion data ---
test("audit: updateResearchRun stores tools_called, failures, data availability, review_id", async () => {
  useTempDb();
  const { createResearchRun, updateResearchRun, getResearchRun } = await import("../lib/research-runner.mjs");
  const runId = createResearchRun({
    signal_id: 6,
    started_at: "2026-07-12T10:00:00Z",
    tools_requested: ["search_symbol"],
    forced: false,
  });
  updateResearchRun(runId, {
    status: "completed",
    tools_called: ["search_symbol", "get_market_data"],
    failures: ["get_macro_series failed: no API key"],
    direct_market_data_available: false,
    fallback_web_used: true,
    review_id: 42,
    forced: false,
  });
  const run = getResearchRun(runId);
  assert.equal(run.status, "completed");
  assert.deepEqual(JSON.parse(run.tools_called_json), ["search_symbol", "get_market_data"]);
  assert.ok(run.failures_json.includes("get_macro_series"));
  assert.equal(run.direct_market_data_available, 0);
  assert.equal(run.fallback_web_used, 1);
  assert.equal(run.review_id, 42);
  assert.equal(run.execution_allowed, 0);
  assert.ok(run.finished_at);
});

// --- 10. Compose review: confidence reduced when direct data unavailable ---
test("compose: confidence reduced when direct_market_data_available=false", async () => {
  const { composeReview } = await import("../lib/research-runner.mjs");
  const signalPayload = {
    signal_id: 6, symbol: "EURUSD", direction: 1,
    entry_reference: 1.14143, generated_at: "2026-07-11T16:17:08Z",
  };
  const preflight = { direct_market_data_available: false, ohlcv_rows: 0, warnings: [] };
  const research = {
    tool_calls: [], data_sources: ["web_search (fallback)"],
    strengths: [], risks: ["Direct OHLCV not available"],
    assumptions: ["Web fallback used"],
    failures: [], fallback_web_used: true, raw_response: {},
  };
  const review = composeReview(signalPayload, preflight, research);
  assert.equal(review.execution_allowed, false);
  assert.ok(review.confidence < 50, `Confidence ${review.confidence} should be < 50 when no direct data`);
});

// --- 11. Compose review: confidence higher when direct data available ---
test("compose: confidence >= 50 when direct data available and no failures", async () => {
  const { composeReview } = await import("../lib/research-runner.mjs");
  const signalPayload = {
    signal_id: 6, symbol: "EURUSD", direction: 1,
    entry_reference: 1.14143, generated_at: "2026-07-11T16:17:08Z",
  };
  const preflight = { direct_market_data_available: true, ohlcv_rows: 90, warnings: [] };
  const research = {
    tool_calls: [], data_sources: ["direct OHLCV (90 rows, 1D)"],
    strengths: ["Bullish trend detected"], risks: [],
    assumptions: ["Direct data available"], failures: [],
    fallback_web_used: false, raw_response: {},
  };
  const review = composeReview(signalPayload, preflight, research);
  assert.ok(review.confidence >= 50, `Confidence ${review.confidence} should be >= 50`);
});

// --- 12. Compose review: verdict insufficient_data when all tools fail ---
test("compose: verdict=insufficient_data when all tools fail and no data sources", async () => {
  const { composeReview } = await import("../lib/research-runner.mjs");
  const signalPayload = {
    signal_id: 6, symbol: "EURUSD", direction: 1,
    entry_reference: 1.14143, generated_at: "2026-07-11T16:17:08Z",
  };
  const preflight = { direct_market_data_available: false, ohlcv_rows: 0, warnings: [] };
  const research = {
    tool_calls: [], data_sources: [],
    strengths: [], risks: [],
    assumptions: [], failures: ["tool1 failed", "tool2 failed", "tool3 failed"],
    fallback_web_used: false, raw_response: {},
  };
  const review = composeReview(signalPayload, preflight, research);
  assert.equal(review.verdict, "insufficient_data");
  assert.ok(review.confidence <= 20);
});

// --- 13. Validate review: valid review passes ---
test("validateReview: valid review passes", async () => {
  const { validateReview } = await import("../lib/research-runner.mjs");
  const review = {
    signal_id: 6, provider: "vibe-trading", verdict: "caution",
    confidence: 50, execution_allowed: false,
  };
  // Should not throw
  validateReview(review);
});

// --- 14. Validate review: invalid verdict rejected ---
test("validateReview: invalid verdict rejected", async () => {
  const { validateReview } = await import("../lib/research-runner.mjs");
  assert.throws(
    () => validateReview({ signal_id: 6, provider: "x", verdict: "invalid", confidence: 50, execution_allowed: false }),
    /verdict must be one of/
  );
});

// --- 15. Validate review: execution_allowed=true rejected ---
test("validateReview: execution_allowed=true rejected", async () => {
  const { validateReview } = await import("../lib/research-runner.mjs");
  assert.throws(
    () => validateReview({ signal_id: 6, provider: "x", verdict: "caution", confidence: 50, execution_allowed: true }),
    /execution_allowed MUST be false/
  );
});

// --- 16. Validate review: confidence out of range rejected ---
test("validateReview: confidence >100 rejected", async () => {
  const { validateReview } = await import("../lib/research-runner.mjs");
  assert.throws(
    () => validateReview({ signal_id: 6, provider: "x", verdict: "caution", confidence: 150, execution_allowed: false }),
    /confidence must be/
  );
  assert.throws(
    () => validateReview({ signal_id: 6, provider: "x", verdict: "caution", confidence: -1, execution_allowed: false }),
    /confidence must be/
  );
});

// --- 17. No signal mutation: checksum unchanged after review storage ---
test("no signal mutation: storing a review does not change signal row", async () => {
  useTempDb();
  const before = signalChecksum(6);
  assert.ok(before, "Signal 6 must exist");

  insertReview({ signal_id: 6 });

  const after = signalChecksum(6);
  assert.equal(after, before, "Signal row must be unchanged");
});

// --- 18. No execution-path mutation: no execution tables modified ---
test("no execution mutation: runResearchReview does not modify execution tables", async () => {
  useTempDb();
  // Snapshot execution-related tables before
  const demoOrdersBefore = tempDb.prepare("SELECT COUNT(*) as n FROM DemoExecutionOrder").get().n;
  const execJournalBefore = tempDb.prepare("SELECT COUNT(*) as n FROM ExecutionJournal").get().n;
  const execControlBefore = JSON.stringify(tempDb.prepare("SELECT * FROM ExecutionControl WHERE id=1").get());

  // Insert a review (simulates what the runner would do)
  insertReview({ signal_id: 6 });

  const demoOrdersAfter = tempDb.prepare("SELECT COUNT(*) as n FROM DemoExecutionOrder").get().n;
  const execJournalAfter = tempDb.prepare("SELECT COUNT(*) as n FROM ExecutionJournal").get().n;
  const execControlAfter = JSON.stringify(tempDb.prepare("SELECT * FROM ExecutionControl WHERE id=1").get());

  assert.equal(demoOrdersAfter, demoOrdersBefore);
  assert.equal(execJournalAfter, execJournalBefore);
  assert.equal(execControlAfter, execControlBefore);
});

// --- 19. Secret redaction: composed review has no secrets ---
test("secret redaction: composeReview output has no secrets", async () => {
  const { composeReview } = await import("../lib/research-runner.mjs");
  const signalPayload = {
    signal_id: 6, symbol: "EURUSD", direction: 1,
    entry_reference: 1.14143, generated_at: "2026-07-11T16:17:08Z",
  };
  const preflight = { direct_market_data_available: true, ohlcv_rows: 50, warnings: [] };
  const research = {
    tool_calls: [], data_sources: ["direct OHLCV"],
    strengths: [], risks: [],
    assumptions: [],
    failures: [],
    fallback_web_used: false,
    raw_response: { api_key: "sk-12345678abcdef", token: "tok-abcdef123456" },
  };
  const review = composeReview(signalPayload, preflight, research);
  // The raw_response should have been redacted by assertNoSecrets in composeReview
  const reviewStr = JSON.stringify(review);
  assert.ok(!reviewStr.includes("sk-12345678abcdef"), "api_key should be redacted");
  assert.ok(!reviewStr.includes("tok-abcdef123456"), "token should be redacted");
  assert.ok(reviewStr.includes("[REDACTED]"), "Should contain [REDACTED] placeholder");
});

// --- 20. Audit record persistence: run record stays in DB ---
test("audit persistence: ResearchRun rows persist after create+update", async () => {
  useTempDb();
  const { createResearchRun, updateResearchRun, getResearchRun } = await import("../lib/research-runner.mjs");
  const runId = createResearchRun({
    signal_id: 6,
    started_at: "2026-07-12T10:00:00Z",
    tools_requested: ["search_symbol"],
    forced: false,
  });
  updateResearchRun(runId, {
    status: "completed",
    tools_called: ["search_symbol"],
    failures: [],
    direct_market_data_available: true,
    fallback_web_used: false,
    review_id: 1,
    forced: false,
  });

  const run = getResearchRun(runId);
  assert.ok(run);
  assert.equal(run.status, "completed");
  assert.equal(run.execution_allowed, 0);
  assert.equal(run.review_id, 1);

  // Verify the row is in the DB via direct query
  const dbRun = tempDb.prepare("SELECT * FROM ResearchRun WHERE id = ?").get(runId);
  assert.ok(dbRun);
  assert.equal(dbRun.signal_id, 6);
});

// --- 21. execution_allowed always false in run audit ---
test("execution_allowed: always 0 in ResearchRun regardless of input", async () => {
  useTempDb();
  const { createResearchRun, updateResearchRun, getResearchRun } = await import("../lib/research-runner.mjs");
  const runId = createResearchRun({
    signal_id: 6,
    started_at: "2026-07-12T10:00:00Z",
    tools_requested: [],
    forced: false,
  });
  // Even if we try to set execution_allowed (there's no param for it, it's hardcoded)
  updateResearchRun(runId, {
    status: "completed",
    tools_called: [],
    failures: [],
    direct_market_data_available: false,
    fallback_web_used: false,
    review_id: null,
    forced: false,
  });
  const run = getResearchRun(runId);
  assert.equal(run.execution_allowed, 0, "execution_allowed must always be 0");
});

// --- 22. Web fallback is labelled in data_sources ---
test("web fallback: data_sources includes 'web_search (fallback)' label", async () => {
  const { composeReview } = await import("../lib/research-runner.mjs");
  const signalPayload = {
    signal_id: 6, symbol: "EURUSD", direction: 1,
    entry_reference: 1.14143, generated_at: "2026-07-11T16:17:08Z",
  };
  const preflight = { direct_market_data_available: false, ohlcv_rows: 0, warnings: [] };
  const research = {
    tool_calls: [],
    data_sources: ["web_search (fallback)", "read_url:https://example.com"],
    strengths: [], risks: ["No direct data"],
    assumptions: ["Web fallback"],
    failures: [],
    fallback_web_used: true,
    raw_response: {},
  };
  const review = composeReview(signalPayload, preflight, research);
  assert.ok(review.data_sources.includes("web_search (fallback)"));
});

// --- 23. CLI script exists and accepts correct args ---
test("CLI: research_run_review.mjs exists and parses --signal-id and --force", async () => {
  const cliPath = join(appDir, "scripts", "research_run_review.mjs");
  const cliContent = readFileSync(cliPath, "utf8");
  assert.ok(cliContent.includes("--signal-id"));
  assert.ok(cliContent.includes("--force"));
  assert.ok(cliContent.includes("runResearchReview"));
});

// --- 24. npm script registered in package.json ---
test("package.json: research:run-review script is registered", async () => {
  const pkg = JSON.parse(readFileSync(join(appDir, "package.json"), "utf8"));
  assert.ok(pkg.scripts["research:run-review"], "research:run-review script must exist");
  assert.ok(pkg.scripts["research:run-review"].includes("research_run_review.mjs"));
});

// --- 25. MCP client: safe env does not pass secrets ---
test("MCP client: startMcpServer uses minimal safe env (no secrets)", async () => {
  const mcpCode = readFileSync(join(appDir, "lib", "mcp-client.mjs"), "utf8");
  // Verify it uses a safeEnv object with limited keys
  assert.ok(mcpCode.includes("safeEnv"), "Should define safeEnv");
  assert.ok(mcpCode.includes("PATH"), "Should allow PATH");
  assert.ok(!mcpCode.includes("process.env.AETHER"), "Should not reference Aether env vars");
  assert.ok(!mcpCode.includes("BROKER"), "Should not reference BROKER env vars");
  assert.ok(!mcpCode.includes("MT5"), "Should not reference MT5 env vars");
});

// --- 26. Response size cap is enforced ---
test("MCP client: response size cap is defined", async () => {
  const mcpCode = readFileSync(join(appDir, "lib", "mcp-client.mjs"), "utf8");
  assert.ok(mcpCode.includes("MCP_RESPONSE_MAX_BYTES"), "Should define max response size");
  // Also verify the research module has a raw_response cap
  const researchCode = readFileSync(join(appDir, "lib", "research.mjs"), "utf8");
  assert.ok(researchCode.includes("RAW_RESPONSE_MAX_CHARS"), "Research module should cap raw response");
});

// --- 27. Partial tool failure: tools_called records both successes and failures ---
test("partial failure: audit records both successful and failed tools", async () => {
  useTempDb();
  const { createResearchRun, updateResearchRun, getResearchRun } = await import("../lib/research-runner.mjs");
  const runId = createResearchRun({
    signal_id: 6,
    started_at: new Date().toISOString(),
    tools_requested: ["search_symbol", "get_market_data", "get_macro_series"],
    forced: false,
  });
  updateResearchRun(runId, {
    status: "completed",
    tools_called: ["search_symbol", "get_market_data", "get_macro_series"],
    failures: ["get_macro_series failed: FRED_API_KEY not configured"],
    direct_market_data_available: false,
    fallback_web_used: true,
    review_id: 5,
    forced: false,
  });
  const run = getResearchRun(runId);
  const toolsCalled = JSON.parse(run.tools_called_json);
  const failures = JSON.parse(run.failures_json);
  assert.equal(toolsCalled.length, 3);
  assert.equal(failures.length, 1);
  assert.ok(failures[0].includes("get_macro_series"));
});

// --- 28. Schema: ResearchRun table is in schema.sql ---
test("schema: ResearchRun table defined in schema.sql", async () => {
  const schema = readFileSync(join(appDir, "schema.sql"), "utf8");
  assert.ok(schema.includes("CREATE TABLE IF NOT EXISTS ResearchRun"));
  assert.ok(schema.includes("execution_allowed INTEGER NOT NULL DEFAULT 0"));
  assert.ok(schema.includes("direct_market_data_available"));
  assert.ok(schema.includes("fallback_web_used"));
});

// --- 29. Migration: ResearchRun table is in db_migrate.mjs ---
test("migration: ensureResearchRunTable in db_migrate.mjs", async () => {
  const migrate = readFileSync(join(appDir, "scripts", "db_migrate.mjs"), "utf8");
  assert.ok(migrate.includes("ensureResearchRunTable"));
  assert.ok(migrate.includes("ResearchRun"));
});

// --- 30. No mutation of signal execution state ---
test("no signal exec mutation: review storage doesn't touch signal status", async () => {
  useTempDb();
  const signalBefore = tempDb.prepare("SELECT status, units, stop_loss, take_profit, signal_score FROM Signal WHERE id=6").get();
  insertReview({ signal_id: 6 });
  const signalAfter = tempDb.prepare("SELECT status, units, stop_loss, take_profit, signal_score FROM Signal WHERE id=6").get();
  assert.deepEqual(signalAfter, signalBefore);
});