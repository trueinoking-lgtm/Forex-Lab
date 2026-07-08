import { marketProfile, markets } from "@/lib/db";
export const dynamic = "force-dynamic";

export default function MarketProfilePage({ searchParams }: { searchParams: { symbol?: string } }) {
  const symbol = searchParams.symbol || "EURUSD";
  const data = marketProfile(symbol);
  const all = markets();
  if (!data) return <p style={{ color: "#9ca3af" }}>Unknown market: {symbol}</p>;
  const m = data.market;
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>{m.symbol} — Market Profile</h1>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
        <Meta label="asset class" value={m.asset_class} />
        <Meta label="session" value={m.session} />
        <Meta label="spread model" value={m.spread_model} />
        <Meta label="volatility" value={m.volatility_profile} />
        <Meta label="default spread" value={`${m.default_spread_bps} bps`} />
        <Meta label="default slippage" value={`${m.default_slippage_bps} bps`} />
        <Meta label="data source" value={m.data_source} />
        <Meta label="status" value={m.enabled ? "active" : "disabled"} />
      </div>
      {m.note && <p style={{ color: "#fbbf24" }}>Note: {m.note}</p>}

      <h2 style={{ color: "#93c5fd" }}>Strategies researched on {m.symbol}</h2>
      {data.runs.length === 0 ? (
        <p style={{ color: "#9ca3af" }}>No backtests yet for this market. Run <code>npm run backtest -- --pair {m.data_source}</code>.</p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>strategy</th><th style={th}>score</th><th style={th}>oos</th>
            <th style={th}>sharpe</th><th style={th}>DD</th><th style={th}>external?</th>
          </tr></thead>
          <tbody>
            {data.runs.map((r: any, i: number) => (
              <tr key={i} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{r.strategy}</td><td style={td}>{r.score?.toFixed?.(1)}</td>
                <td style={td}>{r.oos_return?.toFixed?.(3)}</td><td style={td}>{r.sharpe?.toFixed?.(2)}</td>
                <td style={td}>{r.max_drawdown?.toFixed?.(3)}</td>
                <td style={td}>{r.is_external ? `✅ ${r.source}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 style={{ color: "#93c5fd", marginTop: 24 }}>Switch market</h2>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {all.map((x) => (
          <a key={x.symbol} href={`/market-profile?symbol=${x.symbol}`}
             style={{ color: x.symbol === symbol ? "#5eead4" : "#93c5fd", fontSize: 13 }}>{x.symbol}</a>
        ))}
      </div>
    </div>
  );
}
function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "10px 14px", minWidth: 120 }}>
      <div style={{ fontSize: 11, color: "#9ca3af" }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{value}</div>
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
