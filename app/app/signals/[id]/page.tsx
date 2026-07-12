import { paperSignals } from "@/lib/db";
import { listReviewsBySignal, type ResearchReview } from "@/lib/research-read";
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

function ResearchReviewCard({ review }: { review: ResearchReview }) {
  return (
    <div style={{ border: "1px solid #1f2937", borderRadius: 8, padding: 16, marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ color: verdictColor(review.verdict), fontWeight: 700, fontSize: 16 }}>
          {review.verdict.toUpperCase()}
        </span>
        <span style={{
          backgroundColor: "#1a1a2e", color: "#f59e0b", padding: "2px 10px",
          borderRadius: 999, fontSize: 12, fontWeight: 600, border: "1px solid #374151"
        }}>
          Advisory only — cannot execute trades
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ color: "#6b7280", fontSize: 12 }}>Review #{review.id}</div>
          <div style={{ color: "#9ca3af", fontSize: 13 }}>{review.provider}</div>
        </div>
        <div>
          <div style={{ color: "#6b7280", fontSize: 12 }}>Confidence</div>
          <div style={{ color: "#e5e7eb", fontSize: 13 }}>{review.confidence !== null ? `${review.confidence}%` : "N/A"}</div>
        </div>
        <div>
          <div style={{ color: "#6b7280", fontSize: 12 }}>Tool</div>
          <div style={{ color: "#9ca3af", fontSize: 13 }}>{review.model_or_tool}</div>
        </div>
      </div>

      {review.malformed && (
        <div style={{ color: "#f59e0b", fontSize: 13, marginBottom: 8 }}>
          ⚠ Some stored JSON fields were malformed and have been omitted.
        </div>
      )}

      {review.summary && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: "#6b7280", fontSize: 12, marginBottom: 2 }}>Summary</div>
          <div style={{ color: "#e5e7eb", fontSize: 14 }}>{review.summary}</div>
        </div>
      )}

      {review.strengths && review.strengths.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: "#5eead4", fontSize: 12, marginBottom: 2 }}>Strengths</div>
          <ul style={{ color: "#9ca3af", fontSize: 13, margin: 0, paddingLeft: 20 }}>
            {review.strengths.map((s: unknown, i: number) => (
              <li key={i}>{String(s)}</li>
            ))}
          </ul>
        </div>
      )}

      {review.risks && review.risks.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: "#f87171", fontSize: 12, marginBottom: 2 }}>Risks</div>
          <ul style={{ color: "#9ca3af", fontSize: 13, margin: 0, paddingLeft: 20 }}>
            {review.risks.map((r: unknown, i: number) => (
              <li key={i}>{String(r)}</li>
            ))}
          </ul>
        </div>
      )}

      {review.assumptions && review.assumptions.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: "#6b7280", fontSize: 12, marginBottom: 2 }}>Assumptions</div>
          <ul style={{ color: "#9ca3af", fontSize: 13, margin: 0, paddingLeft: 20 }}>
            {review.assumptions.map((a: unknown, i: number) => (
              <li key={i}>{String(a)}</li>
            ))}
          </ul>
        </div>
      )}

      {review.data_sources && review.data_sources.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: "#6b7280", fontSize: 12, marginBottom: 2 }}>Data Sources</div>
          <div style={{ color: "#9ca3af", fontSize: 13 }}>{review.data_sources.join(", ")}</div>
        </div>
      )}

      {review.tool_calls && review.tool_calls.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: "#6b7280", fontSize: 12, marginBottom: 2 }}>Tools Called</div>
          <ul style={{ color: "#9ca3af", fontSize: 13, margin: 0, paddingLeft: 20 }}>
            {review.tool_calls.map((tc: unknown, i: number) => {
              const obj = tc as Record<string, unknown>;
              return <li key={i}>{obj.tool ? String(obj.tool) : String(tc)}</li>;
            })}
          </ul>
        </div>
      )}

      <div style={{ color: "#6b7280", fontSize: 12, marginBottom: 8 }}>
        Created: {review.created_at} · execution_allowed: false · research_only: true
      </div>

      {review.raw_response && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ color: "#6b7280", fontSize: 12, cursor: "pointer" }}>
            Expand raw response
          </summary>
          <pre style={{
            color: "#9ca3af", fontSize: 12, overflow: "auto",
            backgroundColor: "#0f0f1a", padding: 12, borderRadius: 6, marginTop: 8
          }}>
            {JSON.stringify(review.raw_response, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

export default function SignalDetailPage({ params }: { params: { id: string } }) {
  const signalId = Number(params.id);
  if (!Number.isInteger(signalId) || signalId <= 0) {
    return <div><h1 style={{ color: "#f87171" }}>Invalid signal ID</h1></div>;
  }

  const signals = paperSignals() as any[];
  const signal = signals.find((s) => s.id === signalId);

  if (!signal) {
    return (
      <div>
        <h1 style={{ color: "#5eead4" }}>Signal #{signalId}</h1>
        <p style={{ color: "#9ca3af" }}>Signal not found.</p>
        <Link href="/signals" style={{ color: "#5eead4" }}>← Back to Signals</Link>
      </div>
    );
  }

  const reviews = listReviewsBySignal(signalId);

  return (
    <div className="animate-in">
      <Link href="/signals" style={{ color: "#5eead4", fontSize: 14 }}>← Back to Signals</Link>
      <h1 style={{ color: "#5eead4" }}>Signal #{signal.id} — {signal.pair}</h1>
      <p style={{ color: "#9ca3af" }}>
        Strategy: {signal.strategy} · Direction: {signal.direction > 0 ? "LONG" : "SHORT"} ·
        Entry: {signal.entry} · SL: {signal.stop_loss} · TP: {signal.take_profit} ·
        Score: {signal.signal_score} · Regime: {signal.regime}
      </p>

      <h2 style={{ color: "#5eead4", marginTop: 32, marginBottom: 8 }}>Research Reviews</h2>
      <span style={{
        backgroundColor: "#1a1a2e", color: "#f59e0b", padding: "2px 10px",
        borderRadius: 999, fontSize: 12, fontWeight: 600, border: "1px solid #374151",
        marginBottom: 12, display: "inline-block"
      }}>
        Advisory only — cannot execute trades
      </span>

      {reviews.length === 0 ? (
        <div style={{ border: "1px solid #1f2937", borderRadius: 8, padding: 16 }}>
          <p style={{ color: "#9ca3af" }}>
            No research reviews yet. Generate a review bundle:
          </p>
          <pre style={{ color: "#5eead4", fontSize: 13, marginTop: 8 }}>
            npm run research:prepare-review -- --signal-id {signal.id} --output review.json
          </pre>
        </div>
      ) : (
        <div>
          {reviews.map((review) => (
            <ResearchReviewCard key={review.id} review={review} />
          ))}
        </div>
      )}

      {/* Run review instruction panel */}
      <div style={{ marginTop: 24, border: "1px solid #1f2937", borderRadius: 8, padding: 16 }}>
        <h3 style={{ color: "#5eead4", fontSize: 15, marginTop: 0, marginBottom: 8 }}>
          Run Vibe Review
        </h3>
        <p style={{ color: "#9ca3af", fontSize: 13, marginBottom: 8 }}>
          Run an advisory research review for this signal using the Vibe-Trading MCP server.
          Reviews are research-only and cannot execute trades.
        </p>
        <pre style={{ color: "#5eead4", fontSize: 13, backgroundColor: "#0f0f1a", padding: 12, borderRadius: 6, overflow: "auto" }}>
          npm run research:run-review -- --signal-id {signal.id}
        </pre>
        <p style={{ color: "#6b7280", fontSize: 12, marginTop: 8 }}>
          Add <code style={{ color: "#9ca3af" }}>--force</code> to override the 24-hour deduplication window.
        </p>
      </div>
    </div>
  );
}