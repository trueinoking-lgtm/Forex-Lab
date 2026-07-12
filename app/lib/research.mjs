// lib/research.mjs — Vibe-Trading MCP research integration (advisory-only).
//
// SAFETY:
// - This module never places, modifies, inspects, or cancels orders.
// - It does not read broker credentials, SSH keys, bridge tokens, or .env contents.
// - It does not change signal state, units, stop loss, take profit, or execution status.
// - All review output is stored with execution_allowed=false and research_only=true.

import Database from "better-sqlite3";
import { join } from "path";

/**
 * Returns the shared DB handle.  In tests, `resetCachedDb()` closes the old
 * handle and deletes the global; the next call re-creates one from the new
 * cwd (or FOREX_LAB_DB_PATH env override).
 * @returns {Database.Database}
 */
function getDb() {
  if (globalThis.__fxResearchDb) return globalThis.__fxResearchDb;
  const dbPath = process.env.FOREX_LAB_DB_PATH ?? join(process.cwd(), "forex_lab.db");
  const db = new Database(dbPath);
  if (process.env.NODE_ENV !== "production") globalThis.__fxResearchDb = db;
  return db;
}

/** @typedef {object} SanitizedSignalPayload
 * @property {number} signal_id
 * @property {string} symbol
 * @property {number} direction
 * @property {string} timeframe
 * @property {string} generated_at
 * @property {number} entry_reference
 * @property {number} stop_loss
 * @property {number} take_profit
 * @property {number} units
 * @property {number|null} confidence
 * @property {string} strategy_name
 * @property {string} rationale
 * @property {{regime:string|null}} market_context
 * @property {false} execution_allowed
 * @property {true} research_only
 */

/** @typedef {object} ResearchReviewInput
 * @property {number} signal_id
 * @property {string} provider
 * @property {string} model_or_tool
 * @property {string} review_type
 * @property {string} verdict
 * @property {number|null} [confidence]
 * @property {string|null} [summary]
 * @property {unknown[]|null} [strengths]
 * @property {unknown[]|null} [risks]
 * @property {unknown[]|null} [assumptions]
 * @property {unknown[]|null} [data_sources]
 * @property {unknown[]|null} [tool_calls]
 * @property {Record<string, unknown>|null} [raw_response]
 * @property {boolean} [execution_allowed]
 * @property {boolean} [research_only]
 */

const RAW_RESPONSE_MAX_CHARS = 100_000;

// Keys that look like they may carry a credential.
const SECRET_KEY_RE = /^(api[_-]?key|apikey|secret|token|password|bridge[_-]?token|mt5[_-]?password|private[_-]?key|broker[_-]?password|credential)$/i;

// Also scan string values for inline `key=longsecret` patterns.
const SECRET_VAL_RE = /(api[_-]?key|apikey|secret|token|password|bridge[_-]?token|mt5[_-]?password|private[_-]?key|broker[_-]?password|credential)\s*[:=]\s*[\w\-./+=]{8,}/i;

/**
 * Recursively walk an object and redact values for keys that look like credentials.
 * Returns a deep-cloned, redacted copy.
 * @param {unknown} obj
 * @returns {unknown}
 */
function deepRedact(obj) {
  if (obj === null || obj === undefined) return obj;
  if (typeof obj !== "object") return obj;
  if (Array.isArray(obj)) return obj.map(deepRedact);
  /** @type {Record<string, unknown>} */
  const out = {};
  for (const [key, val] of Object.entries(obj)) {
    if (SECRET_KEY_RE.test(key)) {
      out[key] = "[REDACTED]";
    } else if (typeof val === "string" && SECRET_VAL_RE.test(val)) {
      out[key] = "[REDACTED]";
    } else {
      out[key] = deepRedact(val);
    }
  }
  return out;
}

/**
 * Redact possible secrets from a raw JSON response and cap size.
 * Returns a JSON string with secrets replaced by "[REDACTED]".
 * @param {Record<string, unknown>|null|undefined} raw
 * @returns {string}
 */
export function redactRawResponse(raw) {
  if (raw === null || raw === undefined) return "{}";
  const redacted = deepRedact(raw);
  let text;
  try {
    text = JSON.stringify(redacted);
  } catch {
    text = String(redacted);
  }
  // Hard size cap to prevent accidental DB bloat or secret leakage in huge payloads.
  if (text.length > RAW_RESPONSE_MAX_CHARS) {
    text = text.slice(0, RAW_RESPONSE_MAX_CHARS) + "...[TRUNCATED]";
  }
  return text;
}

/**
 * Throw if a serialized value looks like it contains a credential.
 * Checks both keys and string values for secret-like patterns.
 * @param {unknown} value
 */
export function assertNoSecrets(value) {
  const redacted = deepRedact(value);
  const original = JSON.stringify(value) ?? "";
  const after = JSON.stringify(redacted) ?? "";
  if (original !== after) {
    throw new Error("Sanitized payload contains possible secret/credential; refusing to export.");
  }
}

/**
 * Export a sanitized, advisory-only payload for a Signal.
 * @param {number} signalId
 * @returns {SanitizedSignalPayload}
 */
export function exportSanitizedSignal(signalId) {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT id, pair, strategy, direction, entry, stop_loss, take_profit,
              signal_score, regime, units, generated_at, status
       FROM Signal WHERE id = ?`
    )
    .get(signalId);

  if (!row) {
    throw new Error(`Signal ${signalId} not found`);
  }

  /** @type {SanitizedSignalPayload} */
  const payload = {
    signal_id: row.id,
    symbol: row.pair,
    direction: row.direction,
    timeframe: "1d", // Signal rows do not yet store a timeframe; daily cadence is the lab default.
    generated_at: row.generated_at,
    entry_reference: row.entry,
    stop_loss: row.stop_loss,
    take_profit: row.take_profit,
    units: row.units ?? 0,
    confidence: row.signal_score ?? null,
    strategy_name: row.strategy,
    rationale: `Generated by ${row.strategy} in ${row.regime ?? "unknown"} regime (status: ${row.status ?? "pending"}).`,
    market_context: { regime: row.regime ?? null },
    execution_allowed: false,
    research_only: true,
  };

  assertNoSecrets(payload);
  return payload;
}

/**
 * @param {ResearchReviewInput} input
 * @param {number|undefined} expectedSignalId
 */
function validateReviewInput(input, expectedSignalId) {
  if (!input || typeof input !== "object") {
    throw new Error("Review input must be a JSON object");
  }
  if (typeof input.signal_id !== "number" || Number.isNaN(input.signal_id)) {
    throw new Error("Review input missing valid signal_id");
  }
  if (expectedSignalId !== undefined && input.signal_id !== expectedSignalId) {
    throw new Error(
      `Signal ID mismatch: CLI expected ${expectedSignalId} but review input has ${input.signal_id}`
    );
  }
  for (const key of ["provider", "model_or_tool", "review_type", "verdict"]) {
    if (typeof input[key] !== "string" || input[key].length === 0) {
      throw new Error(`Review input missing required field: ${key}`);
    }
  }

  // Verify the referenced signal exists (foreign-key safety).
  const db = getDb();
  const exists = db.prepare("SELECT 1 FROM Signal WHERE id = ?").get(input.signal_id);
  if (!exists) {
    throw new Error(`Signal ${input.signal_id} not found; cannot store review`);
  }
}

/**
 * @param {unknown} value
 * @returns {string|null}
 */
function normalizeOptionalArray(value) {
  if (value === undefined || value === null) return null;
  if (Array.isArray(value)) {
    return value.length === 0 ? null : JSON.stringify(value);
  }
  throw new Error("Expected array or null for JSON list field");
}

/**
 * Store an advisory review, forcing execution_allowed=false and research_only=true.
 * @param {ResearchReviewInput} input
 * @param {number|undefined} [expectedSignalId]
 * @returns {{reviewId: number, executionAllowed: false, researchOnly: true}}
 */
export function storeResearchReview(input, expectedSignalId) {
  validateReviewInput(input, expectedSignalId);

  // Safety: advisory-only flags are always forced, regardless of caller input.
  const executionAllowed = false;
  const researchOnly = true;

  const rawRedacted = redactRawResponse(input.raw_response ?? null);

  const db = getDb();
  const result = db
    .prepare(
      `INSERT INTO ResearchReview
       (signal_id, provider, model_or_tool, review_type, verdict, confidence,
        summary, strengths_json, risks_json, assumptions_json, data_sources_json,
        tool_calls_json, raw_response_json, execution_allowed, research_only, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))`
    )
    .run(
      input.signal_id,
      input.provider,
      input.model_or_tool,
      input.review_type,
      input.verdict,
      input.confidence ?? null,
      input.summary ?? null,
      normalizeOptionalArray(input.strengths),
      normalizeOptionalArray(input.risks),
      normalizeOptionalArray(input.assumptions),
      normalizeOptionalArray(input.data_sources),
      normalizeOptionalArray(input.tool_calls),
      rawRedacted,
      executionAllowed ? 1 : 0,
      researchOnly ? 1 : 0
    );

  return {
    reviewId: Number(result.lastInsertRowid),
    executionAllowed,
    researchOnly,
  };
}

// ---------------------------------------------------------------------------
// Read APIs (Phase 2)
// ---------------------------------------------------------------------------

/**
 * Parse a stored JSON column safely. Returns null on malformed/empty.
 * @param {string|null} text
 * @returns {unknown[]|null}
 */
function safeParseJsonArray(text) {
  if (!text) return null;
  try {
    const val = JSON.parse(text);
    return Array.isArray(val) ? val : null;
  } catch {
    return null;
  }
}

/**
 * Parse a stored raw_response_json column safely.
 * @param {string|null} text
 * @returns {Record<string, unknown>|null}
 */
function safeParseJsonObject(text) {
  if (!text) return null;
  try {
    const val = JSON.parse(text);
    return typeof val === "object" && !Array.isArray(val) ? val : null;
  } catch {
    return null;
  }
}

/**
 * Check if a stored JSON column is malformed (non-empty but unparseable).
 * @param {string|null} text
 * @returns {boolean}
 */
function isMalformedJson(text) {
  if (!text) return false;
  try {
    JSON.parse(text);
    return false;
  } catch {
    return true;
  }
}

/**
 * Convert a raw DB row to a safe, client-friendly review object.
 * Always forces execution_allowed=false and research_only=true.
 * @param {Record<string, unknown>} row
 * @returns {object}
 */
function rowToReview(row) {
  return {
    id: row.id,
    signal_id: row.signal_id,
    provider: row.provider,
    model_or_tool: row.model_or_tool,
    review_type: row.review_type,
    verdict: row.verdict,
    confidence: row.confidence,
    summary: row.summary,
    strengths: safeParseJsonArray(row.strengths_json),
    risks: safeParseJsonArray(row.risks_json),
    assumptions: safeParseJsonArray(row.assumptions_json),
    data_sources: safeParseJsonArray(row.data_sources_json),
    tool_calls: safeParseJsonArray(row.tool_calls_json),
    raw_response: safeParseJsonObject(row.raw_response_json),
    execution_allowed: false, // always false — advisory only
    research_only: true,
    created_at: row.created_at,
    malformed: false,
  };
}

/**
 * Check all JSON columns of a review row for malformed data.
 * @param {Record<string, unknown>} row
 * @returns {boolean}
 */
function checkMalformed(row) {
  return (
    isMalformedJson(row.strengths_json) ||
    isMalformedJson(row.risks_json) ||
    isMalformedJson(row.assumptions_json) ||
    isMalformedJson(row.data_sources_json) ||
    isMalformedJson(row.tool_calls_json) ||
    isMalformedJson(row.raw_response_json)
  );
}

/**
 * List research reviews, newest-first, with pagination and optional signal filter.
 * @param {{signalId?: number, limit?: number, offset?: number, verdict?: string}} opts
 * @returns {{reviews: object[], total: number}}
 */
export function listResearchReviews(opts = {}) {
  const db = getDb();
  const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200);
  const offset = Math.max(opts.offset ?? 0, 0);
  const signalId = opts.signalId;
  const verdict = opts.verdict;

  /** @type {string[]} */
  const whereParts = [];
  /** @type {unknown[]} */
  const params = [];
  if (signalId !== undefined && Number.isInteger(signalId)) {
    whereParts.push("signal_id = ?");
    params.push(signalId);
  }
  if (verdict && typeof verdict === "string") {
    whereParts.push("verdict = ?");
    params.push(verdict);
  }
  const where = whereParts.length > 0 ? "WHERE " + whereParts.join(" AND ") : "";

  const total = db
    .prepare(`SELECT COUNT(*) as n FROM ResearchReview ${where}`)
    .get(...params).n;
  const rows = db
    .prepare(
      `SELECT * FROM ResearchReview ${where}
       ORDER BY created_at DESC, id DESC
       LIMIT ? OFFSET ?`
    )
    .all(...params, limit, offset);

  const reviews = rows.map((r) => {
    const review = rowToReview(r);
    review.malformed = checkMalformed(r);
    return review;
  });

  return { reviews, total };
}

/**
 * Get a single research review by ID. Returns null if not found.
 * @param {number} reviewId
 * @returns {object|null}
 */
export function getResearchReview(reviewId) {
  const db = getDb();
  const row = db
    .prepare("SELECT * FROM ResearchReview WHERE id = ?")
    .get(reviewId);
  if (!row) return null;

  const review = rowToReview(row);
  review.malformed = checkMalformed(row);
  return review;
}

/**
 * List all reviews for a given signal, newest-first.
 * @param {number} signalId
 * @returns {object[]}
 */
export function listReviewsBySignal(signalId) {
  return listResearchReviews({ signalId, limit: 200 }).reviews;
}

// Exposed only for tests; production code should not close the shared db handle.
export function _closeResearchDb() {
  if (globalThis.__fxResearchDb) {
    globalThis.__fxResearchDb.close();
    delete globalThis.__fxResearchDb;
  }
}