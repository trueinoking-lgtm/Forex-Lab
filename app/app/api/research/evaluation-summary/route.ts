// GET /api/research/evaluation-summary — aggregate evaluation metrics.
import { NextResponse } from "next/server";
import { computeEvaluationSummary } from "@/lib/research-eval-read";

export const dynamic = "force-dynamic";

export async function GET() {
  const summary = computeEvaluationSummary();
  return NextResponse.json(summary);
}