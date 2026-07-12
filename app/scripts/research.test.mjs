// scripts/research.test.mjs — tests for Vibe-Trading MCP research integration.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import Database from "better-sqlite3";
import { mkdtempSync, writeFileSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { fileURLToPath } from "url";
import { execFileSync } from "node:child_process";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const appDir = join(__dirname, "..");
const prodDbPath = join(appDir, "forex_lab.db");

let tempDir;
let tempDb;

/**
 * Create a temporary directory with a copy of the production DB using the
 * sqlite3 CLI .backup command (synchronous).
 * Sets FOREX_LAB_DB_PATH env so lib/research.mjs connects to the temp copy.
 * Returns the temp dir path.
 */
function useTempDb() {
  // Close any cached handle from previous test.
  const g = globalThis;
  if (g.__fxResearchDb) {
    g.__fxResearchDb.close();
    delete g.__fxResearchDb;
  }

  if (tempDir) {
    rmSync(tempDir, { recursive: true, force: true });
  }

  tempDir = mkdtempSync(join(tmpdir(), "aether-research-test-"));
  const destPath = join(tempDir, "forex_lab.db");
  execFileSync("sqlite3", [prodDbPath, `.backup ${destPath}`]);
  tempDb = new Database(destPath);

  // Point the research module at the temp DB.
  process.env.FOREX_LAB_DB_PATH = destPath;
  return tempDir;
}

before(() => {
  // noop
});

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

async function loadResearch() {
  return import("../lib/research.mjs");
}

// ---------------------------------------------------------------------------
// Sanitized signal export tests
// ---------------------------------------------------------------------------

test("exportSanitizedSignal returns allowed fields only and forces advisory flags", async () => {
  useTempDb();
  const { exportSanitizedSignal } = await loadResearch();
  const payload = exportSanitizedSignal(6);

  assert.equal(payload.signal_id, 6);
  assert.equal(payload.symbol, "EURUSD");
  assert.ok([1, -1].includes(payload.direction));
  assert.equal(payload.timeframe, "1d");
  assert.equal(typeof payload.generated_at, "string");
  assert.equal(payload.entry_reference, 1.14143);
  assert.equal(payload.stop_loss, 1.135);
  assert.equal(payload.take_profit, 1.15);
  assert.equal(payload.units, 2000);
  assert.equal(payload.confidence, 63);
  assert.equal(payload.strategy_name, "rsi");
  assert.ok(typeof payload.rationale, "string");
  assert.deepEqual(payload.market_context, { regime: "trend" });
  assert.equal(payload.execution_allowed, false);
  assert.equal(payload.research_only, true);

  const keys = Object.keys(payload).sort();
  const allowed = [
    "signal_id",
    "symbol",
    "direction",
    "timeframe",
    "generated_at",
    "entry_reference",
    "stop_loss",
    "take_profit",
    "units",
    "confidence",
    "strategy_name",
    "rationale",
    "market_context",
    "execution_allowed",
    "research_only",
  ].sort();
  assert.deepEqual(keys, allowed);
});

test("exportSanitizedSignal rejects unknown signal IDs", async () => {
  useTempDb();
  const { exportSanitizedSignal } = await loadResearch();
  assert.throws(() => exportSanitizedSignal(999999), /not found/);
});

test("exportSanitizedSignal rejects payloads containing possible secrets", async () => {
  useTempDb();
  const { exportSanitizedSignal } = await loadResearch();

  // Disable FK so we can insert a malicious row without needing a Strategy.
  tempDb.pragma("foreign_keys = OFF");
  tempDb.prepare(
    `INSERT INTO Signal (pair, strategy, direction, entry, stop_loss, take_profit,
                         signal_score, regime, units, generated_at, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    "api_key=secret12345678",
    "rsi",
    1,
    1.1,
    1.095,
    1.105,
    50,
    "trend",
    1000,
    new Date().toISOString(),
    "paper"
  );
  tempDb.pragma("foreign_keys = ON");

  const row = tempDb.prepare("SELECT id FROM Signal WHERE pair = ?").get("api_key=secret12345678");
  assert.throws(() => exportSanitizedSignal(row.id), /possible secret/);
});

// ---------------------------------------------------------------------------
// Review storage tests
// ---------------------------------------------------------------------------

test("storeResearchReview stores review with execution_allowed forced false", async () => {
  useTempDb();
  const { storeResearchReview } = await loadResearch();
  const result = storeResearchReview({
    signal_id: 6,
    provider: "vibe-trading",
    model_or_tool: "mcp__vibe_trading__global-macro",
    review_type: "macro_fx",
    verdict: "neutral",
    confidence: 0.6,
    summary: "Test review",
    strengths: ["Clear regime"],
    risks: ["Staleness"],
    assumptions: ["No gap"],
    data_sources: ["yfinance"],
    tool_calls: [{ tool: "get_market_data", args: { codes: ["EURUSD=X"] } }],
    raw_response: { advisory: "hold", note: "no execution" },
    execution_allowed: true, // should be ignored
    research_only: false, // should be ignored
  });

  assert.equal(result.executionAllowed, false);
  assert.equal(result.researchOnly, true);
  assert.ok(Number.isInteger(result.reviewId));

  const stored = tempDb.prepare("SELECT * FROM ResearchReview WHERE id = ?").get(result.reviewId);
  assert.equal(stored.signal_id, 6);
  assert.equal(stored.execution_allowed, 0);
  assert.equal(stored.research_only, 1);
  assert.equal(stored.provider, "vibe-trading");
  assert.equal(JSON.parse(stored.strengths_json)[0], "Clear regime");
  assert.equal(JSON.parse(stored.raw_response_json).advisory, "hold");
});

test("storeResearchReview rejects mismatched signal IDs", async () => {
  useTempDb();
  const { storeResearchReview } = await loadResearch();
  assert.throws(
    () =>
      storeResearchReview(
        {
          signal_id: 5,
          provider: "vibe-trading",
          model_or_tool: "global-macro",
          review_type: "macro",
          verdict: "neutral",
        },
        6
      ),
    /mismatch/
  );
});

test("storeResearchReview rejects missing signal_id", async () => {
  useTempDb();
  const { storeResearchReview } = await loadResearch();
  assert.throws(
    () =>
      storeResearchReview({
        provider: "vibe-trading",
        model_or_tool: "global-macro",
        review_type: "macro",
        verdict: "neutral",
      }),
    /missing valid signal_id/
  );
});

test("storeResearchReview rejects unknown signal IDs", async () => {
  useTempDb();
  const { storeResearchReview } = await loadResearch();
  assert.throws(
    () =>
      storeResearchReview({
        signal_id: 999999,
        provider: "vibe-trading",
        model_or_tool: "global-macro",
        review_type: "macro",
        verdict: "neutral",
      }),
    /not found/
  );
});

test("storeResearchReview rejects non-array JSON list fields", async () => {
  useTempDb();
  const { storeResearchReview } = await loadResearch();
  assert.throws(
    () =>
      storeResearchReview({
        signal_id: 6,
        provider: "vibe-trading",
        model_or_tool: "global-macro",
        review_type: "macro",
        verdict: "neutral",
        strengths: "not-an-array",
      }),
    /Expected array/
  );
});

// ---------------------------------------------------------------------------
// Secret redaction tests
// ---------------------------------------------------------------------------

test("redactRawResponse caps size and redacts secrets", async () => {
  useTempDb();
  const { redactRawResponse } = await loadResearch();
  const redacted = redactRawResponse({ bridge_token: "abc123456789", note: "ok" });
  const parsed = JSON.parse(redacted);
  assert.equal(parsed.bridge_token, "[REDACTED]");
  assert.equal(parsed.note, "ok");
});

test("assertNoSecrets detects credentials in nested JSON", async () => {
  const { assertNoSecrets } = await loadResearch();
  assert.throws(
    () => assertNoSecrets({ nested: { api_key: "sk_1234567890abcdef" } }),
    /possible secret/
  );
  // Non-secret payloads should pass.
  assertNoSecrets({ symbol: "EURUSD", units: 2000 });
});

// ---------------------------------------------------------------------------
// CLI tests — run scripts from appDir with FOREX_LAB_DB_PATH pointing to temp DB
// ---------------------------------------------------------------------------

test("CLI export-signal returns valid sanitized JSON", async () => {
  useTempDb();
  const out = execFileSync(
    "node",
    ["scripts/research_export_signal.mjs", "--signal-id", "6"],
    { cwd: appDir, encoding: "utf8", env: { ...process.env } }
  );
  const payload = JSON.parse(out);
  assert.equal(payload.signal_id, 6);
  assert.equal(payload.execution_allowed, false);
  assert.equal(payload.research_only, true);
});

test("CLI export-signal rejects missing signal-id", async () => {
  useTempDb();
  assert.throws(
    () =>
      execFileSync("node", ["scripts/research_export_signal.mjs"], {
        cwd: appDir,
        env: { ...process.env },
      }),
    /Missing --signal-id/
  );
});

test("CLI store-review stores advisory review from file", async () => {
  useTempDb();
  const inputPath = join(tempDir, "review.json");
  writeFileSync(
    inputPath,
    JSON.stringify({
      signal_id: 6,
      provider: "vibe-trading",
      model_or_tool: "mcp__vibe_trading__global-macro",
      review_type: "macro_fx",
      verdict: "cautious",
      confidence: 0.55,
      summary: "CLI test review",
    })
  );
  const out = execFileSync(
    "node",
    ["scripts/research_store_review.mjs", "--signal-id", "6", "--input", inputPath],
    { cwd: appDir, encoding: "utf8", env: { ...process.env } }
  );
  const result = JSON.parse(out);
  assert.equal(result.executionAllowed, false);
  assert.equal(result.researchOnly, true);
  const stored = tempDb.prepare("SELECT id FROM ResearchReview WHERE id = ?").get(result.reviewId);
  assert.ok(stored);
});

test("CLI store-review rejects mismatched signal-id", async () => {
  useTempDb();
  const inputPath = join(tempDir, "review.json");
  writeFileSync(
    inputPath,
    JSON.stringify({
      signal_id: 5,
      provider: "vibe-trading",
      model_or_tool: "global-macro",
      review_type: "macro",
      verdict: "neutral",
    })
  );
  assert.throws(
    () =>
      execFileSync(
        "node",
        ["scripts/research_store_review.mjs", "--signal-id", "6", "--input", inputPath],
        { cwd: appDir, env: { ...process.env } }
      ),
    /mismatch/
  );
});

// ---------------------------------------------------------------------------
// Schema test
// ---------------------------------------------------------------------------

test("ResearchReview table exists after migration", async () => {
  useTempDb();
  const row = tempDb
    .prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ResearchReview'")
    .get();
  assert.ok(row);
});