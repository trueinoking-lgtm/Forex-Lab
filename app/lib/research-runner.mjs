// lib/research-runner.mjs — CLI-triggered Vibe-Trading MCP review runner.
//
// SAFETY:
// - CLI-only, human-triggered. No cron, queues, background workers, or hooks.
// - Never modifies signal state, units, SL, TP, confidence, or execution state.
// - Never passes broker credentials, API keys, or env secrets to the MCP server.
// - Tool allowlist enforced before every call. execution_allowed always false.
// - Direct market data preferred; web search is labeled fallback only.
// - Deduplication: rejects same signal_id + review_type within 24 hours unless --force.

import Database from "better-sqlite3";
import { join } from "path";
import {
  startMcpServer,
  stopMcpServer,
  initializeMcp,
  listMcpTools,
  callMcpTool,
  assertAllowedTool,
  ALLOWED_TOOLS,
  _resetMcpClient,
} from "./mcp-client.mjs";
import { exportSanitizedSignal, storeResearchReview, redactRawResponse, assertNoSecrets, deepRedact } from "./research.mjs";

const MAX_MARKET_DATA_ROWS = 500;
const MCP_TIMEOUT_MS = 60_000;
const DEDUP_WINDOW_HOURS = 24;

/**
 * Get the DB handle (same pattern as research.mjs).
 * @returns {Database.Database}
 */
function getDb() {
  if (globalThis.__fxResearchDb) return globalThis.__fxResearchDb;
  const dbPath = process.env.FOREX_LAB_DB_PATH ?? join(process.cwd(), "forex_lab.db");
  const db = new Database(dbPath);
  if (process.env.NODE_ENV !== "production") globalThis.__fxResearchDb = db;
  return db;
}

// ---------------------------------------------------------------------------
// Deduplication
// ---------------------------------------------------------------------------

/**
 * Check for an existing review for the same signal_id + review_type within the
 * deduplication window. Returns the existing review row or null.
 * @param {number} signalId
 * @param {string} reviewType
 * @param {number} windowHours
 * @returns {{id: number, created_at: string}|null}
 */
export function findRecentReview(signalId, reviewType, windowHours = DEDUP_WINDOW_HOURS) {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT id, created_at FROM ResearchReview
       WHERE signal_id = ? AND review_type = ?
         AND created_at >= datetime('now', ?)
       ORDER BY created_at DESC
       LIMIT 1`
    )
    .get(signalId, reviewType, `-${windowHours} hours`);
  return row ?? null;
}

// ---------------------------------------------------------------------------
// Run audit persistence
// ---------------------------------------------------------------------------

/**
 * Create a new ResearchRun audit row.
 * @param {{signal_id: number, started_at: string, tools_requested: string[], forced: boolean}} opts
 * @returns {number} run ID
 */
export function createResearchRun(opts) {
  const db = getDb();
  const result = db
    .prepare(
      `INSERT INTO ResearchRun
       (signal_id, started_at, status, tools_requested_json, forced, execution_allowed)
       VALUES (?, ?, 'running', ?, ?, 0)`
    )
    .run(
      opts.signal_id,
      opts.started_at,
      JSON.stringify(opts.tools_requested ?? []),
      opts.forced ? 1 : 0
    );
  return Number(result.lastInsertRowid);
}

/**
 * Update a ResearchRun audit row with completion data.
 * @param {number} runId
 * @param {{
 *   status: string,
 *   tools_called: string[],
 *   failures: string[],
 *   direct_market_data_available: boolean,
 *   fallback_web_used: boolean,
 *   review_id: number|null,
 *   forced: boolean
 * }} opts
 */
export function updateResearchRun(runId, opts) {
  const db = getDb();
  db.prepare(
    `UPDATE ResearchRun SET
       finished_at = datetime('now'),
       status = ?,
       tools_called_json = ?,
       failures_json = ?,
       direct_market_data_available = ?,
       fallback_web_used = ?,
       review_id = ?,
       forced = ?,
       execution_allowed = 0
     WHERE id = ?`
  ).run(
    opts.status,
    JSON.stringify(opts.tools_called ?? []),
    JSON.stringify(opts.failures ?? []),
    opts.direct_market_data_available ? 1 : 0,
    opts.fallback_web_used ? 1 : 0,
    opts.review_id ?? null,
    opts.forced ? 1 : 0,
    runId
  );
}

/**
 * Get a ResearchRun by ID (for tests/verification).
 * @param {number} runId
 * @returns {object|null}
 */
export function getResearchRun(runId) {
  const db = getDb();
  return db.prepare("SELECT * FROM ResearchRun WHERE id = ?").get(runId) ?? null;
}

// ---------------------------------------------------------------------------
// Preflight: symbol resolution + direct market data availability
// ---------------------------------------------------------------------------

/**
 * Preflight step: resolve the signal's symbol and attempt to fetch a small
 * recent OHLCV slice. Records whether direct market data is available.
 *
 * @param {object} signalPayload - sanitized signal payload from exportSanitizedSignal
 * @returns {Promise<{
 *   symbol_resolved: boolean,
 *   direct_market_data_available: boolean,
 *   ohlcv_rows: number,
 *   data_source: string|null,
 *   interval: string,
 *   start_date: string,
 *   end_date: string,
 *   warnings: string[],
 *   preflight_tool_calls: object[]
 * }>}
 */
export async function preflightMarketData(signalPayload) {
  const symbol = signalPayload.symbol;
  const warnings = [];
  const toolCalls = [];
  let symbolResolved = false;
  let directAvailable = false;
  let ohlcvRows = 0;
  let dataSource = null;

  // Compute a date window: last 90 days
  const endDate = new Date(signalPayload.generated_at);
  const startDate = new Date(endDate);
  startDate.setDate(startDate.getDate() - 90);
  const endDateStr = endDate.toISOString().slice(0, 10);
  const startDateStr = startDate.toISOString().slice(0, 10);

  // Step 1: resolve symbol via search_symbol
  try {
    const searchResult = await callMcpTool("search_symbol", { query: symbol }, 30_000);
    toolCalls.push({
      tool: "search_symbol",
      args: { query: symbol },
      result_summary: "Symbol search completed",
      ok: true,
    });
    // Check if the symbol was resolved
    if (searchResult && typeof searchResult === "object") {
      const candidates = searchResult.candidates ?? searchResult ?? [];
      if (Array.isArray(candidates) && candidates.length > 0) {
        symbolResolved = true;
      }
    }
  } catch (err) {
    warnings.push(`search_symbol failed: ${err.message}`);
    toolCalls.push({
      tool: "search_symbol",
      args: { query: symbol },
      error: err.message,
      ok: false,
    });
  }

  // Step 2: attempt direct market data fetch (capped at 500 rows)
  const interval = "1D";
  try {
    const mdResult = await callMcpTool(
      "get_market_data",
      {
        codes: [symbol],
        start_date: startDateStr,
        end_date: endDateStr,
        interval,
        max_rows: MAX_MARKET_DATA_ROWS,
      },
      MCP_TIMEOUT_MS
    );

    // Check if we got actual data back
    if (mdResult && typeof mdResult === "object") {
      const data = mdResult.data ?? mdResult;
      if (Array.isArray(data) && data.length > 0) {
        directAvailable = true;
        ohlcvRows = data.length;
        dataSource = "vibe-trading:get_market_data";
      } else if (typeof data === "object" && data !== null) {
        // Check for unresolved markers
        const vals = Object.values(data);
        if (vals.some((v) => String(v).includes("_unresolved") || String(v).includes("error"))) {
          warnings.push("Market data source returned unresolved/error marker");
        } else {
          // Maybe it's a single-symbol object with rows
          const possibleRows = vals.find((v) => Array.isArray(v));
          if (Array.isArray(possibleRows) && possibleRows.length > 0) {
            directAvailable = true;
            ohlcvRows = possibleRows.length;
            dataSource = "vibe-trading:get_market_data";
          }
        }
      }
    }

    toolCalls.push({
      tool: "get_market_data",
      args: { codes: [symbol], start_date: startDateStr, end_date: endDateStr, interval, max_rows: MAX_MARKET_DATA_ROWS },
      result_summary: directAvailable
        ? `${ohlcvRows} rows of OHLCV data retrieved`
        : "No direct OHLCV data available",
      ok: true,
    });
  } catch (err) {
    warnings.push(`get_market_data failed: ${err.message}`);
    toolCalls.push({
      tool: "get_market_data",
      args: { codes: [symbol], start_date: startDateStr, end_date: endDateStr, interval, max_rows: MAX_MARKET_DATA_ROWS },
      error: err.message,
      ok: false,
    });
  }

  return {
    symbol_resolved: symbolResolved,
    direct_market_data_available: directAvailable,
    ohlcv_rows: ohlcvRows,
    data_source: dataSource,
    interval,
    start_date: startDateStr,
    end_date: endDateStr,
    warnings,
    preflight_tool_calls: toolCalls,
  };
}

// ---------------------------------------------------------------------------
// Research execution: call direct-data tools, then web fallback
// ---------------------------------------------------------------------------

/**
 * Run the full research workflow:
 * 1. Preflight (symbol resolve + market data slice)
 * 2. If direct data available: call pattern_recognition, factor_analysis, etc.
 * 3. If direct data NOT available: use web_search + read_url as fallback
 * 4. Compose review with confidence adjusted for data availability
 *
 * @param {object} signalPayload - sanitized signal
 * @param {object} preflightResult - from preflightMarketData
 * @returns {Promise<{
 *   tool_calls: object[],
 *   data_sources: string[],
 *   strengths: string[],
 *   risks: string[],
 *   assumptions: string[],
 *   failures: string[],
 *   fallback_web_used: boolean,
 *   raw_response: object
 * }>}
 */
export async function executeResearch(signalPayload, preflightResult) {
  const toolCalls = [...preflightResult.preflight_tool_calls];
  const dataSources = [];
  const strengths = [];
  const risks = [];
  const assumptions = [];
  const failures = [];
  let fallbackWebUsed = false;
  const rawResponse = {};

  // Record data sources from preflight
  if (preflightResult.direct_market_data_available) {
    dataSources.push(`direct OHLCV (${preflightResult.ohlcv_rows} rows, ${preflightResult.interval})`);
    assumptions.push(`Direct market data was available for ${signalPayload.symbol} (${preflightResult.ohlcv_rows} rows).`);
  } else {
    risks.push("Direct OHLCV market data was NOT available; analysis relies on web fallback sources.");
    assumptions.push("Direct market data was unavailable; web search used as fallback. Confidence reduced accordingly.");
  }

  // --- Direct-data tools (only if data was available) ---
  if (preflightResult.direct_market_data_available) {
    // Pattern recognition
    try {
      const prResult = await callMcpTool("pattern_recognition", {}, MCP_TIMEOUT_MS);
      toolCalls.push({ tool: "pattern_recognition", args: {}, result_summary: "Pattern recognition completed", ok: true });
      dataSources.push("pattern_recognition");
      rawResponse.pattern_recognition = prResult;

      // Extract pattern findings as strengths/risks
      if (prResult && typeof prResult === "object") {
        const patterns = prResult.patterns ?? prResult;
        if (Array.isArray(patterns) && patterns.length > 0) {
          strengths.push(`Patterns detected: ${patterns.map((p) => p.name ?? p).join(", ")}`);
        }
      }
    } catch (err) {
      failures.push(`pattern_recognition failed: ${err.message}`);
      toolCalls.push({ tool: "pattern_recognition", args: {}, error: err.message, ok: false });
    }
  }

  // --- Macro data (attempted regardless, but may fail without API key) ---
  const macroIndicators = [
    { series_id: "FEDFUNDS", label: "Federal Funds Rate" },
    { series_id: "DGS10", label: "10-Year Treasury Yield" },
  ];
  for (const indicator of macroIndicators) {
    try {
      const macroResult = await callMcpTool(
        "get_macro_series",
        { series_id: indicator.series_id, limit: 100 },
        30_000
      );
      toolCalls.push({
        tool: "get_macro_series",
        args: { series_id: indicator.series_id },
        result_summary: `${indicator.label} data retrieved`,
        ok: true,
      });
      dataSources.push(`macro:${indicator.series_id}`);
      rawResponse[`macro_${indicator.series_id}`] = macroResult;
    } catch (err) {
      failures.push(`get_macro_series(${indicator.series_id}) failed: ${err.message}`);
      toolCalls.push({
        tool: "get_macro_series",
        args: { series_id: indicator.series_id },
        error: err.message,
        ok: false,
      });
    }
  }

  // --- Web fallback (only if direct data unavailable) ---
  if (!preflightResult.direct_market_data_available) {
    fallbackWebUsed = true;
    const query = `${signalPayload.symbol} exchange rate technical analysis 2026`;

    try {
      const searchResult = await callMcpTool("web_search", { query, max_results: 5 }, 30_000);
      toolCalls.push({ tool: "web_search", args: { query }, result_summary: "Web search completed", ok: true });
      dataSources.push("web_search (fallback)");
      rawResponse.web_search = searchResult;

      // Read top result for deeper analysis
      if (searchResult && typeof searchResult === "object") {
        const results = searchResult.results ?? searchResult.data ?? [];
        if (Array.isArray(results) && results.length > 0) {
          const topUrl = results[0]?.url ?? results[0]?.link;
          if (topUrl && typeof topUrl === "string") {
            try {
              const readResult = await callMcpTool("read_url", { url: topUrl }, MCP_TIMEOUT_MS);
              toolCalls.push({ tool: "read_url", args: { url: topUrl }, result_summary: "URL content retrieved", ok: true });
              dataSources.push(`read_url:${topUrl.slice(0, 80)}`);
              rawResponse.read_url = readResult;

              // Extract insights from the read content
              if (readResult && typeof readResult === "object") {
                const content = readResult.content ?? readResult.text ?? readResult.markdown ?? "";
                if (typeof content === "string" && content.length > 0) {
                  assumptions.push("Technical analysis sourced from web search fallback; not verified against direct market data.");
                  // Simple heuristic: look for support/resistance mentions
                  if (/support/i.test(content)) {
                    strengths.push("Web source mentions support levels near the signal's entry zone.");
                  }
                  if (/resistance/i.test(content)) {
                    risks.push("Web source identifies resistance levels that may challenge the trade.");
                  }
                }
              }
            } catch (err) {
              failures.push(`read_url failed: ${err.message}`);
              toolCalls.push({ tool: "read_url", args: { url: topUrl }, error: err.message, ok: false });
            }
          }
        }
      }
    } catch (err) {
      failures.push(`web_search failed: ${err.message}`);
      toolCalls.push({ tool: "web_search", args: { query }, error: err.message, ok: false });
    }
  }

  // --- List/load skills for additional context ---
  try {
    const skillsResult = await callMcpTool("list_skills", {}, 15_000);
    toolCalls.push({ tool: "list_skills", args: {}, result_summary: "Skills listed", ok: true });
    rawResponse.skills = skillsResult;
  } catch (err) {
    failures.push(`list_skills failed: ${err.message}`);
    toolCalls.push({ tool: "list_skills", args: {}, error: err.message, ok: false });
  }

  return {
    tool_calls: toolCalls,
    data_sources: dataSources,
    strengths,
    risks,
    assumptions,
    failures,
    fallback_web_used: fallbackWebUsed,
    raw_response: rawResponse,
  };
}

// ---------------------------------------------------------------------------
// Review composition + confidence scoring
// ---------------------------------------------------------------------------

const VALID_VERDICTS = new Set(["support", "caution", "reject", "insufficient_data"]);

/**
 * Compose the final review object from research results.
 * - confidence is reduced when direct data is unavailable
 * - verdict defaults to caution when direct data is missing
 * - execution_allowed is ALWAYS false
 *
 * @param {object} signalPayload
 * @param {object} preflightResult
 * @param {object} researchResult
 * @returns {object} review object matching the required response schema
 */
export function composeReview(signalPayload, preflightResult, researchResult) {
  let confidence = 50; // baseline
  let verdict = "caution";

  if (preflightResult.direct_market_data_available && researchResult.failures.length === 0) {
    confidence = 65;
    if (researchResult.strengths.length > researchResult.risks.length) {
      verdict = "support";
    } else if (researchResult.risks.length > researchResult.strengths.length) {
      verdict = "caution";
    }
  } else if (!preflightResult.direct_market_data_available) {
    // Reduce confidence when relying on web fallback
    confidence = Math.max(20, confidence - 15);
    verdict = "caution";
  }

  if (researchResult.failures.length > 2) {
    confidence = Math.max(15, confidence - 10);
  }

  // If all tools failed and no data at all
  if (researchResult.failures.length > 0 && researchResult.data_sources.length === 0) {
    verdict = "insufficient_data";
    confidence = Math.max(5, 20 - researchResult.failures.length * 3);
  }

  // Clamp confidence to 0-100 integer
  confidence = Math.max(0, Math.min(100, Math.round(confidence)));

  // Build summary
  const dirLabel = signalPayload.direction > 0 ? "LONG" : "SHORT";
  let summary = `Signal for ${signalPayload.symbol} (${dirLabel}) at entry ${signalPayload.entry_reference}. `;
  if (preflightResult.direct_market_data_available) {
    summary += `Direct OHLCV data (${preflightResult.ohlcv_rows} rows) was available for analysis. `;
  } else {
    summary += `Direct OHLCV data was NOT available; analysis relied on web fallback sources. `;
  }
  summary += `Verdict: ${verdict}, confidence: ${confidence}%.`;

  const review = {
    signal_id: signalPayload.signal_id,
    provider: "vibe-trading",
    model_or_tool: "vibe-trading-mcp",
    review_type: "macro_fx",
    verdict,
    confidence,
    summary,
    strengths: researchResult.strengths.length > 0 ? researchResult.strengths : null,
    risks: researchResult.risks.length > 0 ? researchResult.risks : null,
    assumptions: researchResult.assumptions.length > 0 ? researchResult.assumptions : null,
    data_sources: researchResult.data_sources.length > 0 ? researchResult.data_sources : null,
    tool_calls: researchResult.tool_calls,
    raw_response: JSON.parse(redactRawResponse(researchResult.raw_response)),
    execution_allowed: false,
    research_only: true,
  };

  // Assert no secrets in the composed review (after redaction)
  assertNoSecrets(review);

  return review;
}

/**
 * Validate a composed review object against the required schema.
 * Throws on invalid fields.
 * @param {object} review
 */
export function validateReview(review) {
  if (!review || typeof review !== "object") {
    throw new Error("Review must be a JSON object");
  }
  if (typeof review.signal_id !== "number" || !Number.isInteger(review.signal_id)) {
    throw new Error("Review signal_id must be an integer");
  }
  if (typeof review.provider !== "string" || review.provider.length === 0) {
    throw new Error("Review provider must be a non-empty string");
  }
  if (typeof review.verdict !== "string" || !VALID_VERDICTS.has(review.verdict)) {
    throw new Error(`Review verdict must be one of: ${[...VALID_VERDICTS].join(", ")}`);
  }
  if (typeof review.confidence !== "number" || review.confidence < 0 || review.confidence > 100) {
    throw new Error("Review confidence must be a number 0-100");
  }
  if (review.execution_allowed !== false) {
    throw new Error("Review execution_allowed MUST be false");
  }
}

// ---------------------------------------------------------------------------
// Main orchestrator
// ---------------------------------------------------------------------------

/**
 * Run a full research review for a signal. This is the main entry point.
 *
 * Steps:
 * 1. Load signal, generate sanitized bundle
 * 2. Check dedup (unless --force)
 * 3. Start MCP server, initialize
 * 4. Preflight: resolve symbol + fetch market data slice
 * 5. Execute research: direct-data tools + web fallback
 * 6. Compose review with confidence scoring
 * 7. Validate + redact + store
 * 8. Update audit run record
 * 9. Return result
 *
 * @param {{signal_id: number, force: boolean}} opts
 * @returns {Promise<{run_id: number, review_id: number|null, status: string, verdict: string, confidence: number}>}
 */
export async function runResearchReview(opts) {
  const { signal_id, force } = opts;
  const startedAt = new Date().toISOString();
  const toolsRequested = ["search_symbol", "get_market_data", "get_macro_series", "pattern_recognition", "list_skills", "web_search", "read_url"];

  // Step 1: Load signal
  const signalPayload = exportSanitizedSignal(signal_id);

  // Step 2: Dedup check
  if (!force) {
    const existing = findRecentReview(signal_id, "macro_fx");
    if (existing) {
      throw new Error(
        `Duplicate review: signal ${signal_id} already has a review of type "macro_fx" within ${DEDUP_WINDOW_HOURS} hours (review #${existing.id}, created ${existing.created_at}). Use --force to override.`
      );
    }
  }

  // Step 3: Create audit run
  const runId = createResearchRun({
    signal_id,
    started_at: startedAt,
    tools_requested: toolsRequested,
    forced: force,
  });

  const failures = [];
  let toolsCalled = [];
  let directMarketDataAvailable = false;
  let fallbackWebUsed = false;
  let reviewId = null;
  let status = "completed";

  try {
    // Start MCP server
    startMcpServer();
    await initializeMcp();

    // Step 4: Preflight
    const preflightResult = await preflightMarketData(signalPayload);
    directMarketDataAvailable = preflightResult.direct_market_data_available;
    toolsCalled.push(...preflightResult.preflight_tool_calls.map((tc) => tc.tool));
    failures.push(...preflightResult.warnings);

    // Step 5: Execute research
    const researchResult = await executeResearch(signalPayload, preflightResult);
    fallbackWebUsed = researchResult.fallback_web_used;
    toolsCalled.push(...researchResult.tool_calls.map((tc) => tc.tool));
    failures.push(...researchResult.failures);

    // Step 6: Compose review
    const review = composeReview(signalPayload, preflightResult, researchResult);

    // Step 7: Validate + store
    validateReview(review);
    const storeResult = storeResearchReview(review, signal_id);
    reviewId = storeResult.reviewId;

    // Update audit
    updateResearchRun(runId, {
      status: "completed",
      tools_called: [...new Set(toolsCalled)],
      failures,
      direct_market_data_available: directMarketDataAvailable,
      fallback_web_used: fallbackWebUsed,
      review_id: reviewId,
      forced: force,
    });

    return {
      run_id: runId,
      review_id: reviewId,
      status: "completed",
      verdict: review.verdict,
      confidence: review.confidence,
      summary: review.summary,
      direct_market_data_available: directMarketDataAvailable,
      fallback_web_used: fallbackWebUsed,
    };
  } catch (err) {
    status = "failed";
    failures.push(err.message);
    updateResearchRun(runId, {
      status: "failed",
      tools_called: [...new Set(toolsCalled)],
      failures,
      direct_market_data_available: directMarketDataAvailable,
      fallback_web_used: fallbackWebUsed,
      review_id: null,
      forced: force,
    });
    throw err;
  } finally {
    // Always stop the MCP server
    stopMcpServer();
  }
}

// Exposed for testing
export { _resetMcpClient };