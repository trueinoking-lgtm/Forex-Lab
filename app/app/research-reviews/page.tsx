import { listResearchReviews, type ResearchReview } from "@/lib/research-read";
import { paperSignals } from "@/lib/db";
import Link from "next/link";

export const dynamic = "force-dynamic";

const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };

function verdictColor(verdict: string): string {
  switch (verdict) {
    case "support": return "#5eead4";
    case "caution": return "#f59e0b";
    case "reject": return "#f87171";
    case "insufficient_data": return "#94a3b8";
    default: return "#9ca3af";
  }
}

export default function ResearchReviewsPage({
  searchParams,
}: {
  searchParams: { signal_id?: string; verdict?: string };
}) {
  const opts: { signalId?: number; verdict?: string } = {};
  if (searchParams.signal_id) {
    const n = Number(searchParams.signal_id);
    if (Number.isInteger(n) && n > 0) opts.signalId = n;
  }
  if (searchParams.verdict) opts.verdict = searchParams.verdict;

  const { reviews, total } = listResearchReviews(opts);

  // Build a signal_id -> symbol map for display
  const signals = paperSignals() as any[];
  const symbolMap = new Map<number, string>();
  for (const s of signals) symbolMap.set(s.id, s.pair);

  const verdicts = ["support", "caution", "reject", "insufficient_data"];

  return (
    <div className="animate-in">
      <h1 style={{ color: "#5eead4" }}>Research Reviews</h1>
      <p style={{ color: "#9ca3af" }}>
        Advisory-only reviews from Vibe-Trading MCP tools. Reviews never mutate signals or execution state.
      </p>
      <span style={{
        backgroundColor: "#1a1a2e", color: "#f59e0b", padding: "2px 10px",
        borderRadius: 999, fontSize: 12, fontWeight: 600, border: "1px solid #374151",
        marginBottom: 16, display: "inline-block"
      }}>
        Advisory only — cannot execute trades
      </span>

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <form style={{ display: "flex", gap: 8 }}>
          <input
            type="number"
            name="signal_id"
            placeholder="Signal ID"
            defaultValue={searchParams.signal_id ?? ""}
            style={{
              backgroundColor: "#0f0f1a", color: "#e5e7eb", border: "1px solid #374151",
              borderRadius: 6, padding: "4px 10px", fontSize: 14, width: 120
            }}
          />
          <select
            name="verdict"
            defaultValue={searchParams.verdict ?? ""}
            style={{
              backgroundColor: "#0f0f1a", color: "#e5e7eb", border: "1px solid #374151",
              borderRadius: 6, padding: "4px 10px", fontSize: 14
            }}
          >
            <option value="">All verdicts</option>
            {verdicts.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
          <button
            type="submit"
            style={{
              backgroundColor: "#1a1a2e", color: "#5eead4", border: "1px solid #374151",
              borderRadius: 6, padding: "4px 14px", fontSize: 14, cursor: "pointer"
            }}
          >Filter</button>
        </form>
        <span style={{ color: "#6b7280", fontSize: 13 }}>{total} review{total !== 1 ? "s" : ""}</span>
      </div>

      {reviews.length === 0 ? (
        <div style={{ border: "1px solid #1f2937", borderRadius: 8, padding: 16 }}>
          <p style={{ color: "#9ca3af" }}>No research reviews found.</p>
          <p style={{ color: "#6b7280", fontSize: 13, marginTop: 8 }}>
            Generate a review bundle: <code style={{ color: "#5eead4" }}>npm run research:prepare-review -- --signal-id &lt;id&gt; --output review.json</code>
          </p>
        </div>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead>
            <tr style={{ color: "#9ca3af", textAlign: "left" }}>
              <th style={th}>ID</th>
              <th style={th}>Signal</th>
              <th style={th}>Symbol</th>
              <th style={th}>Verdict</th>
              <th style={th}>Confidence</th>
              <th style={th}>Provider / Tool</th>
              <th style={th}>Created</th>
            </tr>
          </thead>
          <tbody>
            {reviews.map((r: ResearchReview) => (
              <tr key={r.id} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>
                  <Link href={`/api/research/reviews/${r.id}`} style={{ color: "#5eead4" }}>{r.id}</Link>
                </td>
                <td style={td}>
                  <Link href={`/signals/${r.signal_id}`} style={{ color: "#5eead4" }}>#{r.signal_id}</Link>
                </td>
                <td style={td}>{symbolMap.get(r.signal_id) ?? "—"}</td>
                <td style={{ ...td, color: verdictColor(r.verdict), fontWeight: 600 }}>
                  {r.verdict}
                </td>
                <td style={td}>{r.confidence !== null ? `${r.confidence}%` : "N/A"}</td>
                <td style={td}>{r.provider} / {r.model_or_tool}</td>
                <td style={{ ...td, color: "#6b7280", fontSize: 13 }}>{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}