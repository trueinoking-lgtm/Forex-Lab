import { pnlSnapshots } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function PerformancePage() {
  const rows = pnlSnapshots() as any[];
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Performance</h1>
      <p style={{ color: "#9ca3af" }}>Account equity and open risk snapshots from <code>npm run paper:update-pnl</code>.</p>
      {rows.length === 0 ? <p>No PnL snapshots yet.</p> :
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>ts</th><th style={th}>account</th><th style={th}>equity</th><th style={th}>open risk</th><th style={th}>daily pnl</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{String(r.ts).slice(0, 19)}</td><td style={td}>{r.account}</td>
                <td style={td}>{r.equity?.toFixed?.(2)}</td><td style={td}>{r.open_risk?.toFixed?.(4)}</td>
                <td style={td}>{r.daily_pnl}</td>
              </tr>
            ))}
          </tbody>
        </table>}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
