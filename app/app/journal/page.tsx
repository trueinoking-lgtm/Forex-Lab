import { journal } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function JournalPage() {
  const rows = journal() as any[];
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Decision Journal</h1>
      <p style={{ color: "#9ca3af" }}>Every paper trade, watchlist entry, and skip is logged with a reason.</p>
      {rows.length === 0 ? <p>No journal entries yet.</p> :
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>ts</th><th style={th}>strategy</th><th style={th}>action</th><th style={th}>reason</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{String(r.ts).slice(0, 19)}</td><td style={td}>{r.strategy}</td>
                <td style={td}><span style={{ color: r.action === "skip" ? "#f87171" : "#5eead4" }}>{r.action}</span></td>
                <td style={td}>{r.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
