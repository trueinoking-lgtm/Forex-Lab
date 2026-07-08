import { markets } from "@/lib/db";
export const dynamic = "force-dynamic";

const CLASS_BADGE: Record<string, string> = {
  forex: "#5eead4", metal: "#fbbf24", crypto: "#a78bfa", index: "#60a5fa", equity: "#f472b6",
};

export default function MarketsPage() {
  const rows = markets();
  const byClass: Record<string, any[]> = {};
  for (const r of rows) (byClass[r.asset_class] ||= []).push(r);
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Markets</h1>
      <p style={{ color: "#9ca3af" }}>
        Multi-market research universe. Each market carries metadata (asset class, session,
        spread model, volatility profile, data source) so the engine applies the right
        cost model. Crypto research mode is present but <strong>disabled</strong> by default.
      </p>
      {Object.keys(byClass).map((cls) => (
        <div key={cls} style={{ marginBottom: 24 }}>
          <h2 style={{ color: CLASS_BADGE[cls] || "#93c5fd" }}>{cls.toUpperCase()}</h2>
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
            <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
              <th style={th}>symbol</th><th style={th}>name</th><th style={th}>session</th>
              <th style={th}>spread</th><th style={th}>slippage</th><th style={th}>vol</th>
              <th style={th}>data</th><th style={th}>status</th>
            </tr></thead>
            <tbody>
              {byClass[cls].map((m) => (
                <tr key={m.symbol} style={{ borderTop: "1px solid #1f2937" }}>
                  <td style={td}><a href={`/market-profile?symbol=${m.symbol}`} style={{ color: "#93c5fd" }}>{m.symbol}</a></td>
                  <td style={td}>{m.name}</td><td style={td}>{m.session}</td>
                  <td style={td}>{m.default_spread_bps}bps</td><td style={td}>{m.default_slippage_bps}bps</td>
                  <td style={td}>{m.volatility_profile}</td><td style={td}>{m.data_source}</td>
                  <td style={td}>{m.enabled ? "✅ active" : "⏸ disabled"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
