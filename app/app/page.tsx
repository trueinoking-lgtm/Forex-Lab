import { topStrategies, paperTrades, pnlSnapshots } from "@/lib/db";

export const dynamic = "force-dynamic";

export default function OverviewPage() {
  const top = topStrategies(5);
  const trades = paperTrades();
  const pnl = pnlSnapshots();
  const open = trades.filter((t) => (t as any).status === "open").length;
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Overview</h1>
      <div style={{ display: "flex", gap: 16, marginBottom: 24 }}>
        <Card label="Top strategy" value={top[0] ? top[0].strategy : "—"} />
        <Card label="Best OOS score" value={top[0] ? top[0].score.toFixed(1) : "—"} />
        <Card label="Open paper trades" value={String(open)} />
        <Card label="PnL snapshots" value={String(pnl.length)} />
      </div>
      <h2 style={{ color: "#93c5fd" }}>Top strategies</h2>
      <Table rows={top} />
    </div>
  );
}
function Card({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "14px 18px", minWidth: 150 }}>
      <div style={{ fontSize: 12, color: "#9ca3af" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
    </div>
  );
}
function Table({ rows }: { rows: any[] }) {
  if (!rows.length) return <p style={{ color: "#9ca3af" }}>No data yet — run backtest + score:strategies.</p>;
  return (
    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
      <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
        <th style={th}>strategy</th><th style={th}>pair</th><th style={th}>score</th>
        <th style={th}>oos</th><th style={th}>sharpe</th><th style={th}>DD</th><th style={th}>robust</th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} style={{ borderTop: "1px solid #1f2937" }}>
            <td style={td}>{r.strategy}</td><td style={td}>{r.pair}</td>
            <td style={td}>{r.score?.toFixed?.(1)}</td><td style={td}>{r.oos_return?.toFixed?.(3)}</td>
            <td style={td}>{r.sharpe?.toFixed?.(2)}</td><td style={td}>{r.max_drawdown?.toFixed?.(3)}</td>
            <td style={td}>{r.robustness?.toFixed?.(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
