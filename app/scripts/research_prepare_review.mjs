// scripts/research_prepare_review.mjs — Bundle a complete review request document.
//
// Produces a single JSON file containing:
// - sanitized signal payload
// - recommended Vibe tools
// - strict research-only instructions
// - required response schema
// - execution_allowed: false
// - generated_at
//
// Usage:
//   npm run research:prepare-review -- --signal-id <id> --output <file>
import { writeFileSync } from "fs";
import { exportSanitizedSignal, assertNoSecrets } from "../lib/research.mjs";

function parseArgs(argv) {
  const sigIdx = argv.indexOf("--signal-id");
  const outIdx = argv.indexOf("--output");
  if (sigIdx === -1 || argv[sigIdx + 1] === undefined) {
    throw new Error("Missing --signal-id argument");
  }
  if (outIdx === -1 || argv[outIdx + 1] === undefined) {
    throw new Error("Missing --output argument");
  }
  const signalId = Number(argv[sigIdx + 1]);
  if (!Number.isInteger(signalId) || signalId <= 0) {
    throw new Error("--signal-id must be a positive integer");
  }
  return { signalId, outputPath: argv[outIdx + 1] };
}

const RECOMMENDED_TOOLS = [
  {
    tool: "mcp__vibe_trading__list_skills",
    reason: "Discover available analytical skills for this signal's market type.",
  },
  {
    tool: "mcp__vibe_trading__get_market_data",
    reason: "Fetch recent OHLCV data for the signal's symbol to verify price action.",
    params_hint: { codes: ["<symbol>"], interval: "1D", max_rows: 100 },
  },
  {
    tool: "mcp__vibe_trading__get_macro_series",
    reason: "Check relevant macro indicators (CPI, FEDFUNDS, DGS10) for forex context.",
  },
  {
    tool: "mcp__vibe_trading__pattern_recognition",
    reason: "Detect chart patterns near the signal's entry price.",
  },
  {
    tool: "mcp__vibe_trading__analyze_trade_journal",
    reason: "If a trade journal is available, analyze historical behavior for this pair.",
  },
];

const RESPONSE_SCHEMA = {
  signal_id: "number — must match the signal_id in this bundle",
  provider: "string — e.g. 'vibe-trading'",
  model_or_tool: "string — which MCP tool or model produced this review",
  review_type: "string — e.g. 'macro_fx', 'technical', 'behavioral'",
  verdict: "support | caution | reject | insufficient_data",
  confidence: "number 0-100 (integer)",
  summary: "string — concise 2-4 sentence assessment",
  strengths: "string[] — bullish/supporting factors",
  risks: "string[] — bearish/concerning factors",
  assumptions: "string[] — assumptions made in the review",
  data_sources: "string[] — data sources consulted",
  tool_calls: "object[] — { tool, args, result_summary } for each tool called",
  raw_response: "object — full raw response from the model/tool",
  execution_allowed: "false — must always be false",
};

const INSTRUCTIONS = `RESEARCH-ONLY ADVISORY REVIEW — SAFETY CONTRACT

1. This review is ADVISORY ONLY. It must never trigger trade execution.
2. Do NOT place, modify, inspect, or cancel orders.
3. Do NOT change the signal's state, units, stop loss, take profit, confidence, or status.
4. Set execution_allowed to false in your response — always.
5. Use only the Vibe-Trading MCP research/analysis tools listed below.
6. Do NOT share credentials, API keys, or environment variables.
7. Base your verdict on the data available — do not fabricate market data.
8. If data is insufficient to form a view, use verdict: "insufficient_data".`;

function main() {
  const { signalId, outputPath } = parseArgs(process.argv.slice(2));
  const signalPayload = exportSanitizedSignal(signalId);

  const bundle = {
    signal: signalPayload,
    recommended_tools: RECOMMENDED_TOOLS,
    instructions: INSTRUCTIONS,
    required_response_schema: RESPONSE_SCHEMA,
    execution_allowed: false,
    generated_at: new Date().toISOString(),
  };

  assertNoSecrets(bundle);
  writeFileSync(outputPath, JSON.stringify(bundle, null, 2) + "\n");
  console.log(JSON.stringify({ ok: true, signal_id: signalId, output: outputPath }, null, 2));
}

try {
  main();
} catch (err) {
  console.error(JSON.stringify({ error: err.message }));
  process.exit(1);
}