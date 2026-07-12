// lib/research-eval.mjs — Retrospective evaluation of research reviews.
//
// SAFETY:
// - Evaluation is retrospective and advisory only.
// - NEVER modifies signal state, review content, or execution state.
// - execution_allowed is ALWAYS false in stored outcomes.
// - No automatic blocking or approval rules.
// - Uses historical market data only (via Vibe-Trading MCP get_market_data).
// - CLI-triggered; no cron, queues, workers, or hooks.

import Database from "better-sqlite3";
import { join } from "path";
import { deepRedact, assertNoSecrets } from "./research.mjs";

const VALID_WINDOWS = new Set(["1d", "3d", "5d", "10d"]);
const WINDOW_DAYS = { "1d": 1, "3d": 3, "5d": 5, "10d": 10 };
const MAX_MARKET_DATA_ROWS = 500;

// ---------------------------------------------------------------------------
// DB access (same pattern as research.mjs)
// ---------------------------------------------------------------------------

function getDb() {
  if (globalThis.__fxResearchDb) return globalThis.__fxResearchDb;
  const dbPath = process.env.FOREX_LAB_DB_PATH ?? join(process.cwd(), "forex_lab.db");
  const db = new Database(dbPath);
  if (process.env.NODE_ENV !== "production") globalThis.__fxResearchDb = db;
  return db;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Validate an evaluation window string.
 * @param {string} window
 */
export function validateWindow(window) {
  if (!VALID_WINDOWS.has(window)) {
    throw new Error(
      `evaluation_window must be one of: ${[...VALID_WINDOWS].join(", ")} (got: ${window})`
    );
  }
}

/**
 * Load a research review by ID from the DB.
 * @param {number} reviewId
 * @returns {{id:number, signal_id:number, verdict:string, confidence:number|null, created_at:string}|null}
 */
export function loadReview(reviewId) {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT id, signal_id, verdict, confidence, created_at
       FROM ResearchReview WHERE id = ?`
    )
    .get(reviewId);
  return row ?? null;
}

/**
 * Load signal data by ID.
 * @param {number} signalId
 * @returns {{id:number, pair:string, direction:number, entry:number, stop_loss:number, take_profit:number, generated_at:string}|null}
 */
export function loadSignal(signalId) {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT id, pair, direction, entry, stop_loss, take_profit, generated_at
       FROM Signal WHERE id = ?`
    )
    .get(signalId);
  return row ?? null;
}

/**
 * Check for an existing outcome for the same review_id + evaluation_window.
 * @param {number} reviewId
 * @param {string} window
 * @returns {{id:number}|null}
 */
export function findExistingOutcome(reviewId, window) {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT id FROM ReviewOutcome
       WHERE review_id = ? AND evaluation_window = ?`
    )
    .get(reviewId, window);
  return row ?? null;
}

// ---------------------------------------------------------------------------
// Market data evaluation logic
// ---------------------------------------------------------------------------

/**
 * Evaluate OHLCV candles against entry/SL/TP for a given direction.
 *
 * For long signals:
 * - TP hit before SL = win
 * - SL hit before TP = loss
 * - neither hit = neutral or unresolved
 *
 * For short signals:
 * - inverse logic
 *
 * If both TP and SL occur in the same candle:
 * - mark ambiguous, do not guess which occurred first
 * - outcome=unresolved, record limitation
 *
 * @param {object} signal - { direction, entry, stop_loss, take_profit }
 * @param {Array<{open:number, high:number, low:number, close:number, timestamp:string}>} candles
 * @returns {object} evaluation result
 */
export function evaluateCandles(signal, candles) {
  const isLong = signal.direction > 0;
  const entry = signal.entry;
  const sl = signal.stop_loss;
  const tp = signal.take_profit;
  const notes = { limitations: [], scoring_rationale: [] };

  if (!candles || candles.length === 0) {
    notes.limitations.push("No market data candles available for evaluation.");
    return {
      outcome: "unresolved",
      take_profit_hit: false,
      stop_loss_hit: false,
      highest_price: null,
      lowest_price: null,
      final_price: null,
      return_pct: null,
      mfe_pct: null,
      mae_pct: null,
      ambiguous: false,
      evaluation_notes: notes,
    };
  }

  // Sort candles by timestamp ascending
  const sorted = [...candles].sort((a, b) => {
    const ta = new Date(a.timestamp || a.date || a.time || "").getTime();
    const tb = new Date(b.timestamp || b.date || b.time || "").getTime();
    return ta - tb;
  });

  let highestPrice = -Infinity;
  let lowestPrice = Infinity;
  let finalPrice = null;
  let tpHit = false;
  let slHit = false;
  let tpHitIndex = -1;
  let slHitIndex = -1;
  let ambiguous = false;

  for (let i = 0; i < sorted.length; i++) {
    const candle = sorted[i];
    const high = candle.high ?? candle.High ?? null;
    const low = candle.low ?? candle.Low ?? null;
    const close = candle.close ?? candle.Close ?? null;

    if (high != null && high > highestPrice) highestPrice = high;
    if (low != null && low < lowestPrice) lowestPrice = low;
    if (i === sorted.length - 1) finalPrice = close;

    if (isLong) {
      // Long: TP is above entry, SL is below entry
      const tpReached = high != null && high >= tp;
      const slReached = low != null && low <= sl;

      if (tpReached && slReached && i === tpHitIndex && i === slHitIndex) {
        // already flagged
      } else if (tpReached && slReached) {
        // Both hit in the same candle — ambiguous
        ambiguous = true;
        tpHit = true;
        slHit = true;
        if (tpHitIndex === -1) tpHitIndex = i;
        if (slHitIndex === -1) slHitIndex = i;
        notes.limitations.push(
          `Both TP (${tp}) and SL (${sl}) were hit in the same candle (index ${i}, timestamp ${candle.timestamp || candle.date || "?"}). Cannot determine which occurred first. Outcome marked as unresolved.`
        );
        break;
      } else if (tpReached && !tpHit) {
        tpHit = true;
        tpHitIndex = i;
        if (!slHit) break; // TP hit first, no need to continue for outcome
      } else if (slReached && !slHit) {
        slHit = true;
        slHitIndex = i;
        if (!tpHit) break; // SL hit first
      }
    } else {
      // Short: TP is below entry, SL is above entry
      const tpReached = low != null && low <= tp;
      const slReached = high != null && high >= sl;

      if (tpReached && slReached) {
        ambiguous = true;
        tpHit = true;
        slHit = true;
        if (tpHitIndex === -1) tpHitIndex = i;
        if (slHitIndex === -1) slHitIndex = i;
        notes.limitations.push(
          `Both TP (${tp}) and SL (${sl}) were hit in the same candle (index ${i}, timestamp ${candle.timestamp || candle.date || "?"}). Cannot determine which occurred first. Outcome marked as unresolved.`
        );
        break;
      } else if (tpReached && !tpHit) {
        tpHit = true;
        tpHitIndex = i;
        if (!slHit) break;
      } else if (slReached && !slHit) {
        slHit = true;
        slHitIndex = i;
        if (!tpHit) break;
      }
    }
  }

  // Clean up infinity values when we had data
  if (highestPrice === -Infinity) highestPrice = null;
  if (lowestPrice === Infinity) lowestPrice = null;

  // Determine outcome
  let outcome;
  if (ambiguous) {
    outcome = "unresolved";
  } else if (tpHit && !slHit) {
    outcome = "win";
  } else if (slHit && !tpHit) {
    outcome = "loss";
  } else if (!tpHit && !slHit) {
    // Neither level hit — classify as neutral or unresolved
    // Use "unresolved" if we don't have enough candles to cover the full window
    outcome = "neutral";
  } else {
    // tpHit && slHit but not ambiguous (hit in different candles, which shouldn't
    // happen because we break on first hit — but guard anyway)
    outcome = "unresolved";
    notes.limitations.push("Unexpected state: both TP and SL hit but not marked ambiguous.");
  }

  // Calculate return_pct, MFE, MAE
  let returnPct = null;
  let mfePct = null;
  let maePct = null;

  if (finalPrice != null && entry != null && entry !== 0) {
    if (isLong) {
      returnPct = ((finalPrice - entry) / entry) * 100;
    } else {
      returnPct = ((entry - finalPrice) / entry) * 100;
    }
  }

  if (highestPrice != null && entry != null && entry !== 0) {
    if (isLong) {
      mfePct = ((highestPrice - entry) / entry) * 100;
    } else {
      mfePct = ((entry - highestPrice) / entry) * 100; // for short, favorable is price going down
      // But wait — for short, the highest price is adverse, not favorable
      // MFE for short = how far price went DOWN from entry
      // MAE for short = how far price went UP from entry
      // We need lowest price for MFE in short
    }
  }

  // Recalculate MFE/MAE properly based on direction
  if (isLong) {
    if (highestPrice != null && entry != null && entry !== 0) {
      mfePct = ((highestPrice - entry) / entry) * 100;
    }
    if (lowestPrice != null && entry != null && entry !== 0) {
      maePct = ((lowestPrice - entry) / entry) * 100; // negative = adverse
    }
  } else {
    // Short: favorable = price goes down, adverse = price goes up
    if (lowestPrice != null && entry != null && entry !== 0) {
      mfePct = ((entry - lowestPrice) / entry) * 100;
    }
    if (highestPrice != null && entry != null && entry !== 0) {
      maePct = ((highestPrice - entry) / entry) * 100; // positive = adverse for short
    }
  }

  return {
    outcome,
    take_profit_hit: tpHit,
    stop_loss_hit: slHit,
    highest_price: highestPrice,
    lowest_price: lowestPrice,
    final_price: finalPrice,
    return_pct: returnPct != null ? Math.round(returnPct * 100) / 100 : null,
    mfe_pct: mfePct != null ? Math.round(mfePct * 100) / 100 : null,
    mae_pct: maePct != null ? Math.round(maePct * 100) / 100 : null,
    ambiguous,
    evaluation_notes: notes,
  };
}

// ---------------------------------------------------------------------------
// Verdict scoring
// ---------------------------------------------------------------------------

/**
 * Score a review verdict against the actual outcome.
 *
 * support:
 *   correct if outcome=win
 *   incorrect if outcome=loss
 *   null if neutral or unresolved
 *
 * reject:
 *   correct if outcome=loss
 *   incorrect if outcome=win
 *   null if neutral or unresolved
 *
 * caution:
 *   correct if outcome=loss or unresolved
 *   partially correct if neutral (verdict_correct=true, with note)
 *   incorrect if strong win (outcome=win and return_pct > 2%)
 *   null if insufficient_data
 *
 * insufficient_data:
 *   not scored — verdict_correct=null
 *
 * @param {string} verdict - support|caution|reject|insufficient_data
 * @param {string} outcome - win|loss|neutral|unresolved
 * @param {number|null} returnPct
 * @returns {{verdict_correct: boolean|null, scoring_rationale: string[]}}
 */
export function scoreVerdict(verdict, outcome, returnPct) {
  const rationale = [];

  if (verdict === "insufficient_data") {
    rationale.push("Verdict is 'insufficient_data' — not scored as correct or incorrect.");
    return { verdict_correct: null, scoring_rationale: rationale };
  }

  if (verdict === "support") {
    if (outcome === "win") {
      rationale.push("Verdict 'support' is CORRECT: predicted favorable outcome and result was a win.");
      return { verdict_correct: true, scoring_rationale: rationale };
    }
    if (outcome === "loss") {
      rationale.push("Verdict 'support' is INCORRECT: predicted favorable outcome but result was a loss.");
      return { verdict_correct: false, scoring_rationale: rationale };
    }
    rationale.push(`Verdict 'support' is not scored for outcome='${outcome}'.`);
    return { verdict_correct: null, scoring_rationale: rationale };
  }

  if (verdict === "reject") {
    if (outcome === "loss") {
      rationale.push("Verdict 'reject' is CORRECT: predicted unfavorable outcome and result was a loss.");
      return { verdict_correct: true, scoring_rationale: rationale };
    }
    if (outcome === "win") {
      rationale.push("Verdict 'reject' is INCORRECT: predicted unfavorable outcome but result was a win.");
      return { verdict_correct: false, scoring_rationale: rationale };
    }
    rationale.push(`Verdict 'reject' is not scored for outcome='${outcome}'.`);
    return { verdict_correct: null, scoring_rationale: rationale };
  }

  if (verdict === "caution") {
    if (outcome === "loss") {
      rationale.push("Verdict 'caution' is CORRECT: cautioned against the trade and result was a loss.");
      return { verdict_correct: true, scoring_rationale: rationale };
    }
    if (outcome === "unresolved") {
      rationale.push("Verdict 'caution' is CORRECT: cautioned against the trade and outcome was unresolved.");
      return { verdict_correct: true, scoring_rationale: rationale };
    }
    if (outcome === "neutral") {
      rationale.push("Verdict 'caution' is PARTIALLY CORRECT: cautioned and outcome was neutral (neither win nor loss).");
      return { verdict_correct: true, scoring_rationale: rationale };
    }
    if (outcome === "win" && returnPct != null && returnPct > 2) {
      rationale.push(`Verdict 'caution' is INCORRECT: cautioned but result was a strong win (return ${returnPct}%).`);
      return { verdict_correct: false, scoring_rationale: rationale };
    }
    if (outcome === "win") {
      rationale.push("Verdict 'caution' is not scored for a marginal win (return <= 2%).");
      return { verdict_correct: null, scoring_rationale: rationale };
    }
  }

  rationale.push(`Verdict '${verdict}' with outcome='${outcome}' — not scored.`);
  return { verdict_correct: null, scoring_rationale: rationale };
}

// ---------------------------------------------------------------------------
// Outcome persistence
// ---------------------------------------------------------------------------

/**
 * Store a ReviewOutcome row. execution_allowed is ALWAYS forced to false.
 * @param {object} opts
 * @returns {number} outcome ID
 */
export function storeReviewOutcome(opts) {
  const db = getDb();

  // Sanitize evaluation_notes — validate raw input first, then redact, so the
  // secret guard actually fires on dirty input instead of pre-redacted data.
  const notesRaw = opts.evaluation_notes ?? {};
  assertNoSecrets(notesRaw);
  const notesRedacted = deepRedact(notesRaw);
  const notesJson = JSON.stringify(notesRedacted);

  const result = db
    .prepare(
      `INSERT OR REPLACE INTO ReviewOutcome
       (review_id, signal_id, evaluated_at, evaluation_window,
        entry_reference, stop_loss, take_profit,
        highest_price, lowest_price, final_price,
        take_profit_hit, stop_loss_hit, outcome,
        return_pct, maximum_favorable_excursion_pct, maximum_adverse_excursion_pct,
        verdict_correct, confidence_score, evaluation_notes_json, data_source,
        execution_allowed)
       VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`
    )
    .run(
      opts.review_id,
      opts.signal_id,
      opts.evaluation_window,
      opts.entry_reference ?? null,
      opts.stop_loss ?? null,
      opts.take_profit ?? null,
      opts.highest_price ?? null,
      opts.lowest_price ?? null,
      opts.final_price ?? null,
      opts.take_profit_hit ? 1 : 0,
      opts.stop_loss_hit ? 1 : 0,
      opts.outcome ?? "unresolved",
      opts.return_pct ?? null,
      opts.mfe_pct ?? null,
      opts.mae_pct ?? null,
      opts.verdict_correct === true ? 1 : opts.verdict_correct === false ? 0 : null,
      opts.confidence_score ?? null,
      notesJson,
      opts.data_source ?? null
    );

  return Number(result.lastInsertRowid);
}

/**
 * Get a ReviewOutcome by ID.
 * @param {number} outcomeId
 * @returns {object|null}
 */
export function getReviewOutcome(outcomeId) {
  const db = getDb();
  const row = db.prepare("SELECT * FROM ReviewOutcome WHERE id = ?").get(outcomeId);
  return row ? rowToOutcome(row) : null;
}

/**
 * List ReviewOutcomes with optional filters.
 * @param {{review_id?:number, signal_id?:number, outcome?:string, limit?:number, offset?:number}} opts
 * @returns {{outcomes: object[], total: number}}
 */
export function listReviewOutcomes(opts = {}) {
  const db = getDb();
  const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200);
  const offset = Math.max(opts.offset ?? 0, 0);

  /** @type {string[]} */
  const whereParts = [];
  /** @type {unknown[]} */
  const params = [];

  if (opts.review_id !== undefined && Number.isInteger(opts.review_id)) {
    whereParts.push("review_id = ?");
    params.push(opts.review_id);
  }
  if (opts.signal_id !== undefined && Number.isInteger(opts.signal_id)) {
    whereParts.push("signal_id = ?");
    params.push(opts.signal_id);
  }
  if (opts.outcome && typeof opts.outcome === "string") {
    whereParts.push("outcome = ?");
    params.push(opts.outcome);
  }

  const where = whereParts.length > 0 ? "WHERE " + whereParts.join(" AND ") : "";

  const total = db
    .prepare(`SELECT COUNT(*) as n FROM ReviewOutcome ${where}`)
    .get(...params).n;

  const rows = db
    .prepare(
      `SELECT * FROM ReviewOutcome ${where}
       ORDER BY evaluated_at DESC, id DESC
       LIMIT ? OFFSET ?`
    )
    .all(...params, limit, offset);

  return { outcomes: rows.map(rowToOutcome), total };
}

/**
 * Convert a DB row to a safe outcome object.
 * Forces execution_allowed=false.
 * @param {Record<string, unknown>} row
 * @returns {object}
 */
function rowToOutcome(row) {
  return {
    id: row.id,
    review_id: row.review_id,
    signal_id: row.signal_id,
    evaluated_at: row.evaluated_at,
    evaluation_window: row.evaluation_window,
    entry_reference: row.entry_reference,
    stop_loss: row.stop_loss,
    take_profit: row.take_profit,
    highest_price: row.highest_price,
    lowest_price: row.lowest_price,
    final_price: row.final_price,
    take_profit_hit: row.take_profit_hit === 1,
    stop_loss_hit: row.stop_loss_hit === 1,
    outcome: row.outcome,
    return_pct: row.return_pct,
    maximum_favorable_excursion_pct: row.maximum_favorable_excursion_pct,
    maximum_adverse_excursion_pct: row.maximum_adverse_excursion_pct,
    verdict_correct:
      row.verdict_correct === 1 ? true : row.verdict_correct === 0 ? false : null,
    confidence_score: row.confidence_score,
    evaluation_notes: safeParseJson(row.evaluation_notes_json),
    data_source: row.data_source,
    execution_allowed: false, // always false — advisory only
  };
}

function safeParseJson(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Evaluation summary service
// ---------------------------------------------------------------------------

/**
 * Compute summary metrics across all review outcomes.
 * @returns {object} summary metrics
 */
export function computeEvaluationSummary() {
  const db = getDb();

  const rows = db.prepare("SELECT * FROM ReviewOutcome").all();

  const totalReviewedSignals = rows.length;
  const resolvedReviews = rows.filter(
    (r) => r.outcome === "win" || r.outcome === "loss" || r.outcome === "neutral"
  ).length;
  const unresolvedCount = rows.filter((r) => r.outcome === "unresolved").length;

  // Verdict accuracy: (verdict_correct=true) / (verdict_correct is not null)
  const scored = rows.filter((r) => r.verdict_correct !== null);
  const correctCount = rows.filter((r) => r.verdict_correct === 1).length;
  const verdictAccuracy = scored.length > 0
    ? Math.round((correctCount / scored.length) * 10000) / 100
    : null;

  // Support win rate: among reviews with verdict=support, how many outcomes were wins
  const supportReviews = rows.filter((r) => {
    const review = db.prepare("SELECT verdict FROM ResearchReview WHERE id = ?").get(r.review_id);
    return review?.verdict === "support";
  });
  const supportWinRate = supportReviews.length > 0
    ? Math.round(
        (supportReviews.filter((r) => r.outcome === "win").length / supportReviews.length) * 10000
      ) / 100
    : null;

  // Caution loss-avoidance rate: among reviews with verdict=caution, how many outcomes were NOT wins
  const cautionReviews = rows.filter((r) => {
    const review = db.prepare("SELECT verdict FROM ResearchReview WHERE id = ?").get(r.review_id);
    return review?.verdict === "caution";
  });
  const cautionLossAvoidanceRate = cautionReviews.length > 0
    ? Math.round(
        (cautionReviews.filter((r) => r.outcome === "loss" || r.outcome === "unresolved").length /
          cautionReviews.length) *
          10000
      ) / 100
    : null;

  // Reject loss rate: among reviews with verdict=reject, how many outcomes were losses
  const rejectReviews = rows.filter((r) => {
    const review = db.prepare("SELECT verdict FROM ResearchReview WHERE id = ?").get(r.review_id);
    return review?.verdict === "reject";
  });
  const rejectLossRate = rejectReviews.length > 0
    ? Math.round(
        (rejectReviews.filter((r) => r.outcome === "loss").length / rejectReviews.length) * 10000
      ) / 100
    : null;

  // Insufficient-data rate
  const insufficientDataReviews = rows.filter((r) => {
    const review = db.prepare("SELECT verdict FROM ResearchReview WHERE id = ?").get(r.review_id);
    return review?.verdict === "insufficient_data";
  });
  const insufficientDataRate = totalReviewedSignals > 0
    ? Math.round(
        (insufficientDataReviews.length / totalReviewedSignals) * 10000
      ) / 100
    : null;

  // Average review confidence
  const confidences = rows
    .map((r) => r.confidence_score)
    .filter((c) => c != null);
  const avgConfidence = confidences.length > 0
    ? Math.round((confidences.reduce((a, b) => a + b, 0) / confidences.length) * 100) / 100
    : null;

  // Confidence calibration buckets
  const buckets = [
    { range: "0-39", min: 0, max: 39, outcomes: { win: 0, loss: 0, neutral: 0, unresolved: 0 }, total: 0 },
    { range: "40-59", min: 40, max: 59, outcomes: { win: 0, loss: 0, neutral: 0, unresolved: 0 }, total: 0 },
    { range: "60-79", min: 60, max: 79, outcomes: { win: 0, loss: 0, neutral: 0, unresolved: 0 }, total: 0 },
    { range: "80-100", min: 80, max: 100, outcomes: { win: 0, loss: 0, neutral: 0, unresolved: 0 }, total: 0 },
  ];

  for (const r of rows) {
    const c = r.confidence_score;
    if (c == null) continue;
    for (const b of buckets) {
      if (c >= b.min && c <= b.max) {
        b.total++;
        if (b.outcomes[r.outcome] !== undefined) {
          b.outcomes[r.outcome]++;
        }
        break;
      }
    }
  }

  // Direct data failure count: outcomes where data_source indicates failure or no data
  const directDataFailureCount = rows.filter(
    (r) => r.data_source == null || r.data_source === "none" || r.data_source.includes("failed")
  ).length;

  return {
    total_reviewed_signals: totalReviewedSignals,
    resolved_reviews: resolvedReviews,
    unresolved_count: unresolvedCount,
    verdict_accuracy: verdictAccuracy,
    support_win_rate: supportWinRate,
    caution_loss_avoidance_rate: cautionLossAvoidanceRate,
    reject_loss_rate: rejectLossRate,
    insufficient_data_rate: insufficientDataRate,
    average_review_confidence: avgConfidence,
    confidence_calibration_buckets: buckets.map((b) => ({
      range: b.range,
      total: b.total,
      outcomes: b.outcomes,
    })),
    direct_data_failure_count: directDataFailureCount,
  };
}

// ---------------------------------------------------------------------------
// Main evaluator — fetches market data via MCP and evaluates the review
// ---------------------------------------------------------------------------

/**
 * Fetch historical OHLCV data for a signal via the Vibe-Trading MCP server.
 * Returns an array of candle objects or throws on error.
 *
 * @param {object} signal - signal row with pair, generated_at
 * @param {number} windowDays - how many days of data to fetch
 * @param {object} mcpClient - { startMcpServer, stopMcpServer, initializeMcp, callMcpTool }
 * @returns {Promise<{candles: Array, data_source: string, warnings: string[]}>}
 */
export async function fetchEvaluationMarketData(signal, windowDays, mcpClient) {
  const warnings = [];
  const symbol = signal.pair;

  // Compute date window: from signal generated_at, extending windowDays forward
  const signalDate = new Date(signal.generated_at);
  const startDate = signalDate.toISOString().slice(0, 10);
  const endDate = new Date(signalDate);
  endDate.setDate(endDate.getDate() + windowDays + 2); // +2 buffer for weekends
  const endDateStr = endDate.toISOString().slice(0, 10);

  let candles = [];
  let dataSource = "none";

  try {
    mcpClient.startMcpServer();
    await mcpClient.initializeMcp();

    const result = await mcpClient.callMcpTool(
      "get_market_data",
      {
        codes: [symbol],
        start_date: startDate,
        end_date: endDateStr,
        interval: "1D",
        max_rows: MAX_MARKET_DATA_ROWS,
      },
      60_000
    );

    // Unwrap the MCP tool-result envelope:
    //   { content: [{ type: "text", text: "..." }], structuredContent, isError }
    const unwrapped = unwrapMcpResult(result);

    if (unwrapped && typeof unwrapped === "object") {
      if (Array.isArray(unwrapped)) {
        candles = unwrapped;
        dataSource = "vibe-trading:get_market_data";
      } else if (typeof unwrapped === "object") {
        // The tool may return a nested structure; look for an array of rows or an _unresolved marker.
        const vals = Object.values(unwrapped);
        const possibleRows = vals.find((v) => Array.isArray(v));
        if (Array.isArray(possibleRows) && possibleRows.length > 0) {
          candles = possibleRows;
          dataSource = "vibe-trading:get_market_data";
        } else if (vals.some((v) => String(v).includes("_unresolved") || String(v).includes("error"))) {
          warnings.push(`Market data returned unresolved/error marker for ${symbol}.`);
        } else {
          warnings.push("Market data returned but no candle rows found.");
        }
      }
    }

    if (candles.length === 0) {
      warnings.push(`No market data available for ${symbol} from ${startDate} to ${endDateStr}.`);
    }
  } catch (err) {
    warnings.push(`MCP get_market_data failed: ${err.message}`);
  } finally {
    try {
      mcpClient.stopMcpServer();
    } catch {
      // ignore
    }
  }

  return { candles, data_source: dataSource, warnings };
}

/**
 * Unwrap an MCP tool-result envelope into the actual payload.
 * Handles:
 *   - { content: [{ type: "text", text: "{...}" }], structuredContent, isError }
 *   - a plain object/array passed through directly
 * @param {unknown} result
 * @returns {unknown}
 */
export function unwrapMcpResult(result) {
  if (result === null || result === undefined) return null;
  if (typeof result !== "object") return result;

  // MCP tool-result envelope
  if ("content" in result && Array.isArray(result.content)) {
    const textParts = [];
    for (const part of result.content) {
      if (part && typeof part === "object") {
        if (typeof part.text === "string") {
          textParts.push(part.text);
        } else if (part.type === "resource" && part.resource?.text) {
          textParts.push(part.resource.text);
        }
      }
    }
    // Prefer structuredContent when present
    if (result.structuredContent !== undefined && result.structuredContent !== null) {
      return result.structuredContent;
    }
    const joined = textParts.join("\n");
    if (joined.trim().length === 0) return null;
    // Try to parse JSON; fall back to raw text
    try {
      return JSON.parse(joined);
    } catch {
      return joined;
    }
  }

  // Already a plain payload
  return result;
}

/**
 * Run a full evaluation for a research review.
 *
 * @param {{review_id: number, window: string, force: boolean, mcpClient?: object}} opts
 * @returns {Promise<object>} evaluation result
 */
export async function evaluateReview(opts) {
  const { review_id, window, force } = opts;

  // Validate window
  validateWindow(window);
  const windowDays = WINDOW_DAYS[window];

  // Load the review
  const review = loadReview(review_id);
  if (!review) {
    throw new Error(`Review ${review_id} not found`);
  }

  // Load the signal
  const signal = loadSignal(review.signal_id);
  if (!signal) {
    throw new Error(`Signal ${review.signal_id} not found`);
  }

  // Dedup check
  if (!force) {
    const existing = findExistingOutcome(review_id, window);
    if (existing) {
      throw new Error(
        `Duplicate evaluation: review ${review_id} already has an outcome for window "${window}" (outcome #${existing.id}). Use --force to override.`
      );
    }
  }

  // Fetch market data
  const mcpClient = opts.mcpClient ?? (await import("./mcp-client.mjs"));
  const { candles, data_source, warnings } = await fetchEvaluationMarketData(
    signal,
    windowDays,
    mcpClient
  );

  // Evaluate candles
  const evalResult = evaluateCandles(signal, candles);

  // Score verdict
  const { verdict_correct, scoring_rationale } = scoreVerdict(
    review.verdict,
    evalResult.outcome,
    evalResult.return_pct
  );

  // Merge notes
  const evaluationNotes = {
    ...evalResult.evaluation_notes,
    scoring_rationale: [
      ...scoring_rationale,
      ...evalResult.evaluation_notes.scoring_rationale,
    ],
    data_warnings: warnings,
    candle_count: candles.length,
    window_days: windowDays,
  };

  // Store the outcome
  const outcomeId = storeReviewOutcome({
    review_id,
    signal_id: review.signal_id,
    evaluation_window: window,
    entry_reference: signal.entry,
    stop_loss: signal.stop_loss,
    take_profit: signal.take_profit,
    highest_price: evalResult.highest_price,
    lowest_price: evalResult.lowest_price,
    final_price: evalResult.final_price,
    take_profit_hit: evalResult.take_profit_hit,
    stop_loss_hit: evalResult.stop_loss_hit,
    outcome: evalResult.outcome,
    return_pct: evalResult.return_pct,
    mfe_pct: evalResult.mfe_pct,
    mae_pct: evalResult.mae_pct,
    verdict_correct,
    confidence_score: review.confidence,
    evaluation_notes: evaluationNotes,
    data_source,
  });

  return {
    outcome_id: outcomeId,
    review_id,
    signal_id: review.signal_id,
    evaluation_window: window,
    outcome: evalResult.outcome,
    take_profit_hit: evalResult.take_profit_hit,
    stop_loss_hit: evalResult.stop_loss_hit,
    highest_price: evalResult.highest_price,
    lowest_price: evalResult.lowest_price,
    final_price: evalResult.final_price,
    return_pct: evalResult.return_pct,
    mfe_pct: evalResult.mfe_pct,
    mae_pct: evalResult.mae_pct,
    verdict_correct,
    confidence_score: review.confidence,
    data_source,
    execution_allowed: false,
    evaluation_notes: evaluationNotes,
  };
}

// Exposed for tests
export function _closeDb() {
  if (globalThis.__fxResearchDb) {
    globalThis.__fxResearchDb.close();
    delete globalThis.__fxResearchDb;
  }
}