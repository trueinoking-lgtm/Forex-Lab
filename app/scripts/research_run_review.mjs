// scripts/research_run_review.mjs — CLI: run a Vibe-Trading MCP research review.
//
// Human-triggered only. No cron, queues, background workers, or hooks.
// Reviews are advisory-only: execution_allowed is ALWAYS false.
// Never modifies signal state, units, SL, TP, confidence, or execution state.
//
// Usage:
//   npm run research:run-review -- --signal-id <id>
//   npm run research:run-review -- --signal-id <id> --force
//
// The --force flag overrides the 24-hour deduplication check.
import { runResearchReview } from "../lib/research-runner.mjs";

function parseArgs(argv) {
  const sigIdx = argv.indexOf("--signal-id");
  if (sigIdx === -1 || argv[sigIdx + 1] === undefined) {
    throw new Error("Missing --signal-id argument. Usage: npm run research:run-review -- --signal-id <id> [--force]");
  }
  const signalId = Number(argv[sigIdx + 1]);
  if (!Number.isInteger(signalId) || signalId <= 0) {
    throw new Error("--signal-id must be a positive integer");
  }
  const force = argv.includes("--force");
  return { signalId, force };
}

async function main() {
  const { signalId, force } = parseArgs(process.argv.slice(2));

  console.error(`[research:run-review] Starting review for signal #${signalId}${force ? " (forced)" : ""}...`);

  const result = await runResearchReview({ signal_id: signalId, force });

  console.log(JSON.stringify({
    ok: true,
    run_id: result.run_id,
    review_id: result.review_id,
    status: result.status,
    verdict: result.verdict,
    confidence: result.confidence,
    summary: result.summary,
    direct_market_data_available: result.direct_market_data_available,
    fallback_web_used: result.fallback_web_used,
    execution_allowed: false,
  }, null, 2));
}

main().catch((err) => {
  console.error(JSON.stringify({ error: err.message, execution_allowed: false }, null, 2));
  process.exit(1);
});