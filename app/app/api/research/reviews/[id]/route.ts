// GET /api/research/reviews/<review-id> — get a single research review.
import { NextResponse } from "next/server";
import { getResearchReview } from "@/lib/research-read";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const reviewId = Number(id);
  if (!Number.isInteger(reviewId) || reviewId <= 0) {
    return NextResponse.json({ error: "review id must be a positive integer" }, { status: 400 });
  }

  const review = getResearchReview(reviewId);
  if (!review) {
    return NextResponse.json({ error: "Review not found" }, { status: 404 });
  }

  return NextResponse.json(review);
}