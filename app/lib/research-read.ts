// lib/research-read.ts — TypeScript wrappers around research.mjs for Next.js pages/APIs.
// Re-exports the read functions with proper typing for server-side use.
import {
  listResearchReviews as _list,
  getResearchReview as _get,
  listReviewsBySignal as _bySignal,
} from "./research.mjs";

export interface ResearchReview {
  id: number;
  signal_id: number;
  provider: string;
  model_or_tool: string;
  review_type: string;
  verdict: string;
  confidence: number | null;
  summary: string | null;
  strengths: unknown[] | null;
  risks: unknown[] | null;
  assumptions: unknown[] | null;
  data_sources: unknown[] | null;
  tool_calls: unknown[] | null;
  raw_response: Record<string, unknown> | null;
  execution_allowed: false;
  research_only: true;
  created_at: string;
  malformed: boolean;
}

export function listResearchReviews(opts?: {
  signalId?: number;
  verdict?: string;
  limit?: number;
  offset?: number;
}): { reviews: ResearchReview[]; total: number } {
  return _list(opts ?? {}) as { reviews: ResearchReview[]; total: number };
}

export function getResearchReview(reviewId: number): ResearchReview | null {
  return _get(reviewId) as ResearchReview | null;
}

export function listReviewsBySignal(signalId: number): ResearchReview[] {
  return _bySignal(signalId) as ResearchReview[];
}