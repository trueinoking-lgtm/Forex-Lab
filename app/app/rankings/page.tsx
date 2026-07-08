import { topStrategies } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function RankingsPage() {
  const rows = topStrategies(50);
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Strategy Rankings</h1>
      <p style={{ color: "#9ca3af" }}>Ranked by composite OOS score with robustness penalty (penalizes lucky-period strategies).</p>
      {rows.length === 0 ? <p>No rankings — run <code>npm run backtest &amp;&amp; npm run score:strategies</code>.</p> :
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>#</th><th style={th}>strategy</th><th style={th}>pair</th><th style={th}>score</th>
            <th style={th}>oos</th><th style={th}>sharpe</th><th style={th}>PF</th><th style={th}>win%</th>
            <th style={th}>trades</th><th style={th}>DD</th><th style={th}>robust</th><th style={th}>beats BH</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{i + 1}</td><td style={td}>{r.strategy}</td><td style={td}>{r.pair}</td>
                <td style={td}>{r.score?.toFixed?.(1)}</td><td style={td}>{r.oos_return?.toFixed?.(3)}</td>
                <td style={td}>{r.sharpe?.toFixed?.(2)}</td><td style={td}>{r.profit_factor?.toFixed?.(2)}</td>
                <td style={td}>{(r.win_rate * 100)?.toFixed?.(0)}%</td><td style={td}>{r.trade_count}</td>
                <td style={td}>{r.max_drawdown?.toFixed?.(3)}</td><td style={td}>{r.robustness?.toFixed?.(2)}</td>
                <td style={td}>{r.beats_bh ? "✅" : "❌"}</td>
              </tr>
            ))}
          </tbody>
        </table>}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
