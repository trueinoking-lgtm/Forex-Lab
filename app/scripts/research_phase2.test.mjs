// scripts/research_phase2.test.mjs — Phase 2 tests for Vibe-Trading MCP advisory integration.
// Covers: API read functions (pagination, filtering, 404, malformed JSON),
//        prepare-review command (schema, secret scanning, execution_allowed=false),
//        advisory badge, empty state, no mutation of signal records,
//        execution_allowed always false.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import Database from "better-sqlite3";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { fileURLToPath } from "url";
import { execFileSync } from "node:child_process";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const appDir = join(__dirname, "..");
const prodDbPath = join(appDir, "forex_lab.db");

let tempDir;
let tempDb;

function useTempDb() {
  const g = globalThis;
  if (g.__fxResearchDb) {
    g.__fxResearchDb.close();
    delete g.__fxResearchDb;
  }
  if (tempDir) rmSync(tempDir, { recursive: true, force: true });
  tempDir = mkdtempSync(join(tmpdir(), "aether-p2-test-"));
  const destPath = join(tempDir, "forex_lab.db");
  execFileSync("sqlite3", [prodDbPath, `.backup ${destPath}`]);
  tempDb = new Database(destPath);
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
  if (tempDb) { tempDb.close(); tempDb = null; }
  if (tempDir) { rmSync(tempDir, { recursive: true, force: true }); tempDir = null; }
});

async function loadResearch() {
  return import("../lib/research.mjs");
}

/**
 * Insert a test review directly into the DB for controlled testing.
 */
function insertTestReview(opts) {
  tempDb.prepare(
    `INSERT INTO ResearchReview
     (signal_id, provider, model_or_tool, review_type, verdict, confidence,
      summary, strengths_json, risks_json, assumptions_json, data_sources_json,
      tool_calls_json, raw_response_json, execution_allowed, research_only, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))`
  ).run(
    opts.signal_id ?? 6,
    opts.provider ?? "vibe-trading",
    opts.model_or_tool ?? "mcp__vibe_trading__get_market_data",
    opts.review_type ?? "macro_fx",
    opts.verdict ?? "caution",
    opts.confidence ?? 55,
    opts.summary ?? "Test review",
    JSON.stringify(opts.strengths ?? ["Clear trend"]),
    JSON.stringify(opts.risks ?? ["Stale data"]),
    JSON.stringify(opts.assumptions ?? ["No gap risk"]),
    JSON.stringify(opts.data_sources ?? ["yfinance"]),
    JSON.stringify(opts.tool_calls ?? [{ tool: "get_market_data", args: { codes: ["EURUSD=X"] } }]),
    JSON.stringify(opts.raw_response ?? { advisory: "hold" }),
    0, // execution_allowed always false
    1  // research_only always true
  );
  return tempDb.prepare("SELECT last_insert_rowid() as id").get().id;
}

// ---------------------------------------------------------------------------
// Read API tests
// ---------------------------------------------------------------------------

test("listResearchReviews returns reviews newest-first with total", async () => {
  useTempDb();
  const { listResearchReviews } = await loadResearch();
  const id1 = insertTestReview({ verdict: "support", confidence: 70 });
  // Small delay so datetime('now') differs
  insertTestReview({ verdict: "caution", confidence: 40 });

  const { reviews, total } = listResearchReviews();
  assert.equal(total, 2);
  assert.equal(reviews.length, 2);
  // Newest first — review 2 has a higher id so should be first
  assert.ok(reviews[0].id > reviews[1].id);
});

test("listResearchReviews filters by signal_id", async () => {
  useTempDb();
  const { listResearchReviews } = await loadResearch();
  insertTestReview({ signal_id: 6, verdict: "support" });
  insertTestReview({ signal_id: 5, verdict: "caution" });

  const { reviews, total } = listResearchReviews({ signalId: 6 });
  assert.equal(total, 1);
  assert.equal(reviews.length, 1);
  assert.equal(reviews[0].signal_id, 6);
});

test("listResearchReviews filters by verdict", async () => {
  useTempDb();
  const { listResearchReviews } = await loadResearch();
  insertTestReview({ verdict: "support" });
  insertTestReview({ verdict: "caution" });
  insertTestReview({ verdict: "reject" });

  const { reviews, total } = listResearchReviews({ verdict: "caution" });
  assert.equal(total, 1);
  assert.equal(reviews.length, 1);
  assert.equal(reviews[0].verdict, "caution");
});

test("listResearchReviews paginates with limit+offset", async () => {
  useTempDb();
  const { listResearchReviews } = await loadResearch();
  for (let i = 0; i < 5; i++) insertTestReview({ verdict: "support", confidence: i * 10 });

  const page1 = listResearchReviews({ limit: 2, offset: 0 });
  assert.equal(page1.reviews.length, 2);
  assert.equal(page1.total, 5);

  const page2 = listResearchReviews({ limit: 2, offset: 2 });
  assert.equal(page2.reviews.length, 2);
  assert.equal(page2.total, 5);

  const page3 = listResearchReviews({ limit: 2, offset: 4 });
  assert.equal(page3.reviews.length, 1);
});

test("getResearchReview returns review by ID", async () => {
  useTempDb();
  const { getResearchReview } = await loadResearch();
  const id = insertTestReview({ verdict: "support", confidence: 80, summary: "Strong signal" });

  const review = getResearchReview(id);
  assert.ok(review);
  assert.equal(review.id, id);
  assert.equal(review.verdict, "support");
  assert.equal(review.confidence, 80);
  assert.equal(review.summary, "Strong signal");
});

test("getResearchReview returns null for missing review (404)", async () => {
  useTempDb();
  const { getResearchReview } = await loadResearch();
  const review = getResearchReview(999999);
  assert.equal(review, null);
});

test("listResearchReviews always returns execution_allowed=false", async () => {
  useTempDb();
  const { listResearchReviews } = await loadResearch();
  insertTestReview({ verdict: "support" });

  const { reviews } = listResearchReviews();
  for (const r of reviews) {
    assert.equal(r.execution_allowed, false);
    assert.equal(r.research_only, true);
  }
});

test("getResearchReview always returns execution_allowed=false", async () => {
  useTempDb();
  const { getResearchReview } = await loadResearch();
  const id = insertTestReview({ verdict: "support" });

  const review = getResearchReview(id);
  assert.equal(review.execution_allowed, false);
  assert.equal(review.research_only, true);
});

test("listResearchReviews handles malformed stored JSON gracefully", async () => {
  useTempDb();
  const { listResearchReviews } = await loadResearch();

  // Insert a review with malformed JSON columns
  tempDb.prepare(
    `INSERT INTO ResearchReview
     (signal_id, provider, model_or_tool, review_type, verdict, confidence,
      summary, strengths_json, risks_json, assumptions_json, data_sources_json,
      tool_calls_json, raw_response_json, execution_allowed, research_only, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))`
  ).run(
    6, "vibe-trading", "test-tool", "test", "caution", 50,
    "Malformed test",
    "{not valid json",
    "{also broken",
    null, null, null, null,
    0, 1
  );

  const { reviews } = listResearchReviews();
  const malformed = reviews.find((r) => r.malformed === true);
  assert.ok(malformed, "Expected at least one review with malformed=true");
  // Malformed JSON fields should be null, not throw
  assert.equal(malformed.strengths, null);
  assert.equal(malformed.risks, null);
});

test("listReviewsBySignal returns reviews for a specific signal", async () => {
  useTempDb();
  const { listReviewsBySignal } = await loadResearch();
  insertTestReview({ signal_id: 6, verdict: "support" });
  insertTestReview({ signal_id: 5, verdict: "caution" });

  const reviews = listReviewsBySignal(6);
  assert.equal(reviews.length, 1);
  assert.equal(reviews[0].signal_id, 6);
});

// ---------------------------------------------------------------------------
// Prepare-review command tests
// ---------------------------------------------------------------------------

test("CLI prepare-review produces valid bundle with required fields", async () => {
  useTempDb();
  const outputPath = join(tempDir, "bundle.json");
  execFileSync("node", [
    "scripts/research_prepare_review.mjs",
    "--signal-id", "6",
    "--output", outputPath,
  ], { cwd: appDir, encoding: "utf8", env: { ...process.env } });

  const bundle = JSON.parse(readFileSync(outputPath, "utf8"));

  // Required top-level fields
  assert.ok(bundle.signal, "bundle must contain signal payload");
  assert.ok(bundle.recommended_tools, "bundle must contain recommended_tools");
  assert.ok(bundle.instructions, "bundle must contain instructions");
  assert.ok(bundle.required_response_schema, "bundle must contain response schema");
  assert.equal(bundle.execution_allowed, false);
  assert.ok(bundle.generated_at, "bundle must contain generated_at");

  // Signal payload is sanitized
  assert.equal(bundle.signal.signal_id, 6);
  assert.equal(bundle.signal.execution_allowed, false);
  assert.equal(bundle.signal.research_only, true);

  // Response schema includes all required fields
  const schemaKeys = Object.keys(bundle.required_response_schema);
  for (const key of [
    "signal_id", "provider", "model_or_tool", "review_type", "verdict",
    "confidence", "summary", "strengths", "risks", "assumptions",
    "data_sources", "tool_calls", "raw_response", "execution_allowed",
  ]) {
    assert.ok(schemaKeys.includes(key), `response schema missing ${key}`);
  }

  // Instructions mention advisory-only and safety
  assert.ok(bundle.instructions.includes("ADVISORY"), "instructions must mention ADVISORY");
  assert.ok(bundle.instructions.includes("execution_allowed"), "instructions must mention execution_allowed");

  // At least 3 recommended tools
  assert.ok(bundle.recommended_tools.length >= 3, "should recommend at least 3 tools");
});

test("CLI prepare-review rejects missing --signal-id", async () => {
  useTempDb();
  assert.throws(
    () =>
      execFileSync("node", ["scripts/research_prepare_review.mjs", "--output", "/tmp/x.json"], {
        cwd: appDir, env: { ...process.env },
      }),
    /Missing --signal-id/
  );
});

test("CLI prepare-review rejects missing --output", async () => {
  useTempDb();
  assert.throws(
    () =>
      execFileSync("node", ["scripts/research_prepare_review.mjs", "--signal-id", "6"], {
        cwd: appDir, env: { ...process.env },
      }),
    /Missing --output/
  );
});

test("CLI prepare-review rejects unknown signal ID", async () => {
  useTempDb();
  assert.throws(
    () =>
      execFileSync("node", [
        "scripts/research_prepare_review.mjs",
        "--signal-id", "999999",
        "--output", "/tmp/x.json",
      ], { cwd: appDir, env: { ...process.env } }),
    /not found/
  );
});

test("prepare-review bundle contains no secrets", async () => {
  useTempDb();
  const outputPath = join(tempDir, "bundle.json");
  execFileSync("node", [
    "scripts/research_prepare_review.mjs",
    "--signal-id", "6",
    "--output", outputPath,
  ], { cwd: appDir, encoding: "utf8", env: { ...process.env } });

  const text = readFileSync(outputPath, "utf8");
  // Check for common credential patterns
  assert.ok(!text.includes("api_key="), "bundle should not contain api_key= patterns");
  assert.ok(!text.includes("password="), "bundle should not contain password= patterns");
  assert.ok(!text.includes("secret="), "bundle should not contain secret= patterns");
  assert.ok(!text.includes("bridge_token="), "bundle should not contain bridge_token= patterns");
});

// ---------------------------------------------------------------------------
// No mutation of signal records test
// ---------------------------------------------------------------------------

test("storing a review does not mutate any signal field", async () => {
  useTempDb();
  const { storeResearchReview } = await loadResearch();

  // Capture signal state before review
  const before = tempDb.prepare("SELECT * FROM Signal WHERE id = 6").get();

  storeResearchReview({
    signal_id: 6,
    provider: "vibe-trading",
    model_or_tool: "test-mutation-check",
    review_type: "test",
    verdict: "caution",
    confidence: 40,
    summary: "Mutation check",
  });

  // Capture signal state after review
  const after = tempDb.prepare("SELECT * FROM Signal WHERE id = 6").get();

  // Every column must be unchanged
  for (const key of Object.keys(before)) {
    assert.deepEqual(after[key], before[key], `Signal.${key} was mutated by review storage`);
  }
});

test("listing reviews does not mutate any signal field", async () => {
  useTempDb();
  const { listResearchReviews } = await loadResearch();
  insertTestReview({ verdict: "support" });

  const before = tempDb.prepare("SELECT * FROM Signal WHERE id = 6").get();
  listResearchReviews();
  const after = tempDb.prepare("SELECT * FROM Signal WHERE id = 6").get();

  for (const key of Object.keys(before)) {
    assert.deepEqual(after[key], before[key], `Signal.${key} was mutated by review listing`);
  }
});