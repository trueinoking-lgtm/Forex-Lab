// lib/research-eval-read.ts — TypeScript wrappers around research-eval.mjs for Next.js.
import {
  listReviewOutcomes as _list,
  getReviewOutcome as _get,
  computeEvaluationSummary as _summary,
} from "./research-eval.mjs";

export interface ReviewOutcome {
  id: number;
  review_id: number;
  signal_id: number;
  evaluated_at: string;
  evaluation_window: string;
  entry_reference: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  highest_price: number | null;
  lowest_price: number | null;
  final_price: number | null;
  take_profit_hit: boolean;
  stop_loss_hit: boolean;
  outcome: string;
  return_pct: number | null;
  maximum_favorable_excursion_pct: number | null;
  maximum_adverse_excursion_pct: number | null;
  verdict_correct: boolean | null;
  confidence_score: number | null;
  evaluation_notes: Record<string, unknown> | null;
  data_source: string | null;
  execution_allowed: false;
}

export function listReviewOutcomes(opts?: {
  review_id?: number;
  signal_id?: number;
  outcome?: string;
  limit?: number;
  offset?: number;
}): { outcomes: ReviewOutcome[]; total: number } {
  return _list(opts ?? {}) as { outcomes: ReviewOutcome[]; total: number };
}

export function getReviewOutcome(outcomeId: number): ReviewOutcome | null {
  return _get(outcomeId) as ReviewOutcome | null;
}

export interface EvaluationSummary {
  total_reviewed_signals: number;
  resolved_reviews: number;
  unresolved_count: number;
  verdict_accuracy: number | null;
  support_win_rate: number | null;
  caution_loss_avoidance_rate: number | null;
  reject_loss_rate: number | null;
  insufficient_data_rate: number | null;
  average_review_confidence: number | null;
  confidence_calibration_buckets: Array<{
    range: string;
    total: number;
    outcomes: Record<string, number>;
  }>;
  direct_data_failure_count: number;
}

export function computeEvaluationSummary(): EvaluationSummary {
  return _summary() as EvaluationSummary;
}