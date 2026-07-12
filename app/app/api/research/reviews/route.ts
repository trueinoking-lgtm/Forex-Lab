// GET /api/research/reviews — list research reviews (advisory-only).
// Supports: ?signal_id=<id>, ?verdict=<verdict>, ?limit=<n>, ?offset=<n>
import { NextResponse } from "next/server";
import { listResearchReviews } from "@/lib/research-read";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const signalId = url.searchParams.get("signal_id");
  const verdict = url.searchParams.get("verdict");
  const limitParam = url.searchParams.get("limit");
  const offsetParam = url.searchParams.get("offset");

  const opts: {
    signalId?: number;
    verdict?: string;
    limit?: number;
    offset?: number;
  } = {};

  if (signalId !== null) {
    const n = Number(signalId);
    if (!Number.isInteger(n) || n <= 0) {
      return NextResponse.json({ error: "signal_id must be a positive integer" }, { status: 400 });
    }
    opts.signalId = n;
  }
  if (verdict !== null) {
    const allowed = ["support", "caution", "reject", "insufficient_data"];
    if (!allowed.includes(verdict)) {
      return NextResponse.json({ error: `verdict must be one of: ${allowed.join(", ")}` }, { status: 400 });
    }
    opts.verdict = verdict;
  }
  if (limitParam !== null) opts.limit = Number(limitParam);
  if (offsetParam !== null) opts.offset = Number(offsetParam);

  const result = listResearchReviews(opts);
  return NextResponse.json(result);
}