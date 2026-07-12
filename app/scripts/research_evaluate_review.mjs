// scripts/research_evaluate_review.mjs — CLI: evaluate a research review retrospectively.
//
// Human-triggered only. No cron, queues, background workers, or hooks.
// Evaluation is retrospective and advisory only. NEVER affects execution.
//
// Usage:
//   npm run research:evaluate-review -- --review-id <id>
//   npm run research:evaluate-review -- --review-id <id> --window 5d
//   npm run research:evaluate-review -- --review-id <id> --window 3d --force
import { evaluateReview } from "../lib/research-eval.mjs";

function parseArgs(argv) {
  const reviewIdx = argv.indexOf("--review-id");
  if (reviewIdx === -1 || argv[reviewIdx + 1] === undefined) {
    throw new Error(
      "Missing --review-id argument. Usage: npm run research:evaluate-review -- --review-id <id> [--window 1d|3d|5d|10d] [--force]"
    );
  }
  const reviewId = Number(argv[reviewIdx + 1]);
  if (!Number.isInteger(reviewId) || reviewId <= 0) {
    throw new Error("--review-id must be a positive integer");
  }

  let window = "5d";
  const windowIdx = argv.indexOf("--window");
  if (windowIdx !== -1 && argv[windowIdx + 1] !== undefined) {
    window = argv[windowIdx + 1];
  }

  const force = argv.includes("--force");
  return { reviewId, window, force };
}

async function main() {
  const { reviewId, window, force } = parseArgs(process.argv.slice(2));

  console.error(
    `[research:evaluate-review] Starting evaluation for review #${reviewId} (window: ${window}${force ? ", forced" : ""})...`
  );

  const result = await evaluateReview({ review_id: reviewId, window, force });

  console.log(
    JSON.stringify(
      {
        ok: true,
        outcome_id: result.outcome_id,
        review_id: result.review_id,
        signal_id: result.signal_id,
        evaluation_window: result.evaluation_window,
        outcome: result.outcome,
        take_profit_hit: result.take_profit_hit,
        stop_loss_hit: result.stop_loss_hit,
        highest_price: result.highest_price,
        lowest_price: result.lowest_price,
        final_price: result.final_price,
        return_pct: result.return_pct,
        mfe_pct: result.mfe_pct,
        mae_pct: result.mae_pct,
        verdict_correct: result.verdict_correct,
        confidence_score: result.confidence_score,
        data_source: result.data_source,
        execution_allowed: false,
        limitations: result.evaluation_notes?.limitations ?? [],
        scoring_rationale: result.evaluation_notes?.scoring_rationale ?? [],
      },
      null,
      2
    )
  );
}

main().catch((err) => {
  console.error(JSON.stringify({ error: err.message, execution_allowed: false }, null, 2));
  process.exit(1);
});