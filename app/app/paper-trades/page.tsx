import { paperTrades } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function PaperTradesPage() {
  const rows = paperTrades() as any[];
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Paper Trades</h1>
      <p style={{ color: "#9ca3af" }}>Simulated account. Risk 0.5–1% per trade. SL/TP mandatory. Updated via <code>npm run paper:update-pnl</code>.</p>
      {rows.length === 0 ? <p>No paper trades yet.</p> :
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>id</th><th style={th}>pair</th><th style={th}>strategy</th><th style={th}>dir</th>
            <th style={th}>entry</th><th style={th}>SL</th><th style={th}>TP</th><th style={th}>risk%</th>
            <th style={th}>status</th><th style={th}>pnl</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{r.id}</td><td style={td}>{r.pair}</td><td style={td}>{r.strategy}</td>
                <td style={td}>{r.direction > 0 ? "LONG" : "SHORT"}</td><td style={td}>{r.entry}</td>
                <td style={td}>{r.stop_loss}</td><td style={td}>{r.take_profit}</td>
                <td style={td}>{r.risk_pct}</td><td style={td}>{r.status}</td><td style={td}>{r.pnl ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
