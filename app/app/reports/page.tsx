import { dailyReports } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function ReportsPage() {
  const rows = dailyReports() as any[];
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Reports</h1>
      <p style={{ color: "#9ca3af" }}>End-of-day reports from <code>npm run report:daily</code>.</p>
      {rows.length === 0 ? <p>No reports yet.</p> :
        rows.map((r) => (
          <div key={r.id} style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: 16, marginBottom: 16 }}>
            <h3 style={{ margin: "0 0 8px" }}>{r.date}</h3>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, color: "#d1d5db" }}>{r.summary}</pre>
          </div>
        ))}
    </div>
  );
}
