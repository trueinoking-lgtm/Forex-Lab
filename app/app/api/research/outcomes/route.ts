// GET /api/research/outcomes — list review outcomes (advisory-only, retrospective).
// Supports: ?review_id=<id>, ?signal_id=<id>, ?outcome=<win|loss|neutral|unresolved>,
//           ?limit=<n>, ?offset=<n>
import { NextResponse } from "next/server";
import { listReviewOutcomes } from "@/lib/research-eval-read";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const reviewId = url.searchParams.get("review_id");
  const signalId = url.searchParams.get("signal_id");
  const outcome = url.searchParams.get("outcome");
  const limitParam = url.searchParams.get("limit");
  const offsetParam = url.searchParams.get("offset");

  const opts: {
    review_id?: number;
    signal_id?: number;
    outcome?: string;
    limit?: number;
    offset?: number;
  } = {};

  if (reviewId !== null) {
    const n = Number(reviewId);
    if (!Number.isInteger(n) || n <= 0) {
      return NextResponse.json({ error: "review_id must be a positive integer" }, { status: 400 });
    }
    opts.review_id = n;
  }
  if (signalId !== null) {
    const n = Number(signalId);
    if (!Number.isInteger(n) || n <= 0) {
      return NextResponse.json({ error: "signal_id must be a positive integer" }, { status: 400 });
    }
    opts.signal_id = n;
  }
  if (outcome !== null) {
    const allowed = ["win", "loss", "neutral", "unresolved"];
    if (!allowed.includes(outcome)) {
      return NextResponse.json({ error: `outcome must be one of: ${allowed.join(", ")}` }, { status: 400 });
    }
    opts.outcome = outcome;
  }
  if (limitParam !== null) opts.limit = Number(limitParam);
  if (offsetParam !== null) opts.offset = Number(offsetParam);

  const result = listReviewOutcomes(opts);
  return NextResponse.json(result);
}