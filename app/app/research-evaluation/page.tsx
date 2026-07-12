import { computeEvaluationSummary, type EvaluationSummary } from "@/lib/research-eval-read";
import Link from "next/link";

export const dynamic = "force-dynamic";

const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };

function fmt(n: number | null, suffix = ""): string {
  if (n === null || n === undefined) return "N/A";
  return `${n}${suffix}`;
}

function metricBox(label: string, value: string, color: string) {
  return (
    <div style={{
      border: "1px solid #1f2937", borderRadius: 8, padding: 16,
      display: "flex", flexDirection: "column", gap: 4
    }}>
      <div style={{ color: "#6b7280", fontSize: 12 }}>{label}</div>
      <div style={{ color, fontSize: 24, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

export default function ResearchEvaluationPage() {
  const summary = computeEvaluationSummary() as EvaluationSummary;

  return (
    <div className="animate-in">
      <Link href="/research-reviews" style={{ color: "#5eead4", fontSize: 14 }}>← Back to Research Reviews</Link>
      <h1 style={{ color: "#5eead4" }}>Research Evaluation Summary</h1>
      <p style={{ color: "#9ca3af" }}>
        Retrospective evaluation of advisory research reviews against historical market data.
        Evaluation is advisory only and never affects trade execution.
      </p>
      <span style={{
        backgroundColor: "#1a1a2e", color: "#94a3b8", padding: "2px 10px",
        borderRadius: 999, fontSize: 12, fontWeight: 600, border: "1px solid #374151",
        marginBottom: 16, display: "inline-block"
      }}>
        Retrospective · advisory only
      </span>

      {/* Summary metrics */}
      <h2 style={{ color: "#5eead4", marginTop: 24, marginBottom: 12 }}>Summary Metrics</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 24 }}>
        {metricBox("Total Reviewed Signals", String(summary.total_reviewed_signals), "#e5e7eb")}
        {metricBox("Resolved Reviews", String(summary.resolved_reviews), "#5eead4")}
        {metricBox("Unresolved Count", String(summary.unresolved_count), "#f59e0b")}
        {metricBox("Direct Data Failures", String(summary.direct_data_failure_count), "#f87171")}
        {metricBox("Verdict Accuracy", summary.verdict_accuracy !== null ? `${summary.verdict_accuracy}%` : "N/A", "#5eead4")}
        {metricBox("Support Win Rate", summary.support_win_rate !== null ? `${summary.support_win_rate}%` : "N/A", "#5eead4")}
        {metricBox("Caution Loss-Avoidance", summary.caution_loss_avoidance_rate !== null ? `${summary.caution_loss_avoidance_rate}%` : "N/A", "#f59e0b")}
        {metricBox("Reject Loss Rate", summary.reject_loss_rate !== null ? `${summary.reject_loss_rate}%` : "N/A", "#f87171")}
        {metricBox("Insufficient-Data Rate", summary.insufficient_data_rate !== null ? `${summary.insufficient_data_rate}%` : "N/A", "#94a3b8")}
        {metricBox("Avg Review Confidence", summary.average_review_confidence !== null ? `${summary.average_review_confidence}%` : "N/A", "#e5e7eb")}
      </div>

      {/* Verdict accuracy table */}
      <h2 style={{ color: "#5eead4", marginTop: 24, marginBottom: 8 }}>Verdict Accuracy</h2>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14, marginBottom: 24 }}>
        <thead>
          <tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>Metric</th>
            <th style={th}>Value</th>
          </tr>
        </thead>
        <tbody>
          <tr style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>Verdict Accuracy</td>
            <td style={td}>{fmt(summary.verdict_accuracy, "%")}</td>
          </tr>
          <tr style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>Support Win Rate</td>
            <td style={td}>{fmt(summary.support_win_rate, "%")}</td>
          </tr>
          <tr style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>Caution Loss-Avoidance Rate</td>
            <td style={td}>{fmt(summary.caution_loss_avoidance_rate, "%")}</td>
          </tr>
          <tr style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>Reject Loss Rate</td>
            <td style={td}>{fmt(summary.reject_loss_rate, "%")}</td>
          </tr>
          <tr style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>Insufficient-Data Rate</td>
            <td style={td}>{fmt(summary.insufficient_data_rate, "%")}</td>
          </tr>
        </tbody>
      </table>

      {/* Confidence calibration table */}
      <h2 style={{ color: "#5eead4", marginTop: 24, marginBottom: 8 }}>Confidence Calibration</h2>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14, marginBottom: 24 }}>
        <thead>
          <tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>Confidence Range</th>
            <th style={th}>Total</th>
            <th style={th}>Wins</th>
            <th style={th}>Losses</th>
            <th style={th}>Neutral</th>
            <th style={th}>Unresolved</th>
          </tr>
        </thead>
        <tbody>
          {summary.confidence_calibration_buckets.map((b) => (
            <tr key={b.range} style={{ borderTop: "1px solid #1f2937" }}>
              <td style={{ ...td, fontWeight: 600, color: "#e5e7eb" }}>{b.range}%</td>
              <td style={td}>{b.total}</td>
              <td style={{ ...td, color: "#5eead4" }}>{b.outcomes.win ?? 0}</td>
              <td style={{ ...td, color: "#f87171" }}>{b.outcomes.loss ?? 0}</td>
              <td style={{ ...td, color: "#94a3b8" }}>{b.outcomes.neutral ?? 0}</td>
              <td style={{ ...td, color: "#f59e0b" }}>{b.outcomes.unresolved ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Additional info */}
      <h2 style={{ color: "#5eead4", marginTop: 24, marginBottom: 8 }}>Data Quality</h2>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14, marginBottom: 24 }}>
        <thead>
          <tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>Metric</th>
            <th style={th}>Value</th>
          </tr>
        </thead>
        <tbody>
          <tr style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>Direct Data Failure Count</td>
            <td style={td}>{summary.direct_data_failure_count}</td>
          </tr>
          <tr style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>Unresolved Count</td>
            <td style={td}>{summary.unresolved_count}</td>
          </tr>
        </tbody>
      </table>

      <div style={{ color: "#6b7280", fontSize: 12, marginTop: 24 }}>
        Evaluation is retrospective and advisory only. execution_allowed is always false.
        No automatic blocking or approval rules.
      </div>
    </div>
  );
}