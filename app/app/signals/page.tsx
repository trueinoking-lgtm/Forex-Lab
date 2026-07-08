import { paperSignals } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function SignalsPage() {
  const rows = paperSignals() as any[];
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Trade Signals</h1>
      <p style={{ color: "#9ca3af" }}>Scored PAPER signals only. No live orders. Each requires SL/TP and passes a risk check.</p>
      {rows.length === 0 ? <p>No signals — run <code>npm run monitor:signals</code> after backtest.</p> :
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>pair</th><th style={th}>strategy</th><th style={th}>dir</th><th style={th}>entry</th>
            <th style={th}>SL</th><th style={th}>TP</th><th style={th}>score</th><th style={th}>regime</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{r.pair}</td><td style={td}>{r.strategy}</td>
                <td style={td}>{r.direction > 0 ? "LONG" : "SHORT"}</td><td style={td}>{r.entry}</td>
                <td style={td}>{r.stop_loss}</td><td style={td}>{r.take_profit}</td>
                <td style={td}>{r.signal_score}</td><td style={td}>{r.regime}</td>
              </tr>
            ))}
          </tbody>
        </table>}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
