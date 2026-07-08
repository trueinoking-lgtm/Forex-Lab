import { strategyProfile } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function StrategyProfilePage() {
  const names = ["ema_crossover", "ema_trend_pullback", "rsi_mean_reversion",
    "macd_trend_confirmation", "london_breakout"];
  const rows = names.flatMap((n) => strategyProfile(n)) as any[];
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Strategy Profile</h1>
      <p style={{ color: "#9ca3af" }}>Per-strategy backtest history (OOS walk-forward).</p>
      {rows.length === 0 ? <p>No profiles — run backtest first.</p> :
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>strategy</th><th style={th}>pair</th><th style={th}>oos</th><th style={th}>in-sample</th>
            <th style={th}>sharpe</th><th style={th}>DD</th><th style={th}>PF</th><th style={th}>win%</th><th style={th}>trades</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{r.strategy}</td><td style={td}>{r.pair}</td>
                <td style={td}>{r.oos_return?.toFixed?.(3)}</td><td style={td}>{r.in_sample_return?.toFixed?.(3)}</td>
                <td style={td}>{r.sharpe?.toFixed?.(2)}</td><td style={td}>{r.max_drawdown?.toFixed?.(3)}</td>
                <td style={td}>{r.profit_factor?.toFixed?.(2)}</td><td style={td}>{(r.win_rate * 100)?.toFixed?.(0)}%</td>
                <td style={td}>{r.trade_count}</td>
              </tr>
            ))}
          </tbody>
        </table>}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
