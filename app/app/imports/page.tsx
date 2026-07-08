import { externalImports } from "@/lib/db";
export const dynamic = "force-dynamic";

const SRC_COLOR: Record<string, string> = {
  tradingview: "#fbbf24", traderdev: "#a78bfa", generic: "#60a5fa",
};

export default function ExternalImportsPage() {
  const rows = externalImports();
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>External Research Imports</h1>
      <p style={{ color: "#9ca3af" }}>
        External platforms (TradingView / PineScript, trader.dev, generic JSON/CSV) are
        <strong> idea sources only</strong>. Every import is validated, labeled
        <code> is_external=1</code>, then <strong>re-scored with OUR spread, slippage,
        walk-forward and paper rules</strong>. The lab is the source of truth — the
        external headline return is never trusted as-is.
      </p>
      <p style={{ color: "#f472b6", fontSize: 13 }}>
        Safety: paper-only. No live execution. No broker credentials. No private keys.
      </p>

      {rows.length === 0 ? (
        <p style={{ color: "#9ca3af" }}>
          No imports yet. Run <code>npm run import:external ../engine/data/sample_imports_tradingview.json</code>
          {" "}to load the sample TradingView set.
        </p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>strategy</th><th style={th}>symbol</th><th style={th}>source</th>
            <th style={th}>ext. return</th><th style={th}>re-scored</th><th style={th}>our cost</th>
            <th style={th}>cost gap</th><th style={th}>robustness</th>
          </tr></thead>
          <tbody>
            {rows.map((r: any, i: number) => (
              <tr key={i} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{r.strategy_name}</td>
                <td style={td}>{r.symbol}</td>
                <td style={td}><span style={{ color: SRC_COLOR[r.source] || "#93c5fd" }}>{r.source}</span></td>
                <td style={td}>{(r.external_net_return * 100).toFixed(1)}%</td>
                <td style={td}><strong>{r.score?.toFixed?.(1)}</strong></td>
                <td style={td}>{r.our_cost_bps}bps</td>
                <td style={td}>{r.cost_gap_bps}bps</td>
                <td style={td}>{r.robustness?.toFixed?.(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
