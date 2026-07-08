import { crossMarketMatrix } from "@/lib/db";
export const dynamic = "force-dynamic";

export default function CrossMarketMatrixPage() {
  const matrix = crossMarketMatrix(5);
  const classes = Object.keys(matrix);
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Strategy Cross-Market Matrix</h1>
      <p style={{ color: "#9ca3af" }}>
        Top strategies per asset class, ranked by our composite score. Native and
        re-scored external strategies appear together — the lab score is the only
        ranking that counts, regardless of where an idea originated.
      </p>
      {classes.length === 0 ? (
        <p style={{ color: "#9ca3af" }}>No scored strategies yet. Run backtests and imports first.</p>
      ) : classes.map((cls) => (
        <div key={cls} style={{ marginBottom: 28 }}>
          <h2 style={{ color: "#93c5fd", textTransform: "uppercase" }}>{cls}</h2>
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
            <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
              <th style={th}>strategy</th><th style={th}>symbol</th><th style={th}>score</th>
              <th style={th}>robustness</th><th style={th}>oos</th><th style={th}>type</th>
            </tr></thead>
            <tbody>
              {matrix[cls].map((r: any, i: number) => (
                <tr key={i} style={{ borderTop: "1px solid #1f2937" }}>
                  <td style={td}>{r.strategy}</td>
                  <td style={td}>{r.pair}</td>
                  <td style={td}><strong>{r.score?.toFixed?.(1)}</strong></td>
                  <td style={td}>{r.robustness?.toFixed?.(3)}</td>
                  <td style={td}>{r.oos_return?.toFixed?.(3)}</td>
                  <td style={td}>
                    {r.is_external
                      ? `✅ ext (${r.source})`
                      : "native"}
                    {r.is_external && r.re_costed_return != null
                      ? ` · re-costed ${r.re_costed_return.toFixed(3)}`
                      : ""}
                  </td>
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
