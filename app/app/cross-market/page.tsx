import { crossMarketMatrix, externalImports } from "@/lib/db";
export const dynamic = "force-dynamic";

export default function CrossMarketMatrixPage() {
  const matrix = crossMarketMatrix(5);
  const classes = Object.keys(matrix);
  const extCount = externalImports().length;
  return (
    <div className="animate-in">
      <h1>Strategy Cross-Market Matrix</h1>
      <p className="lead">
        Top strategies per asset class, ranked by our composite score. Native and
        re-scored external strategies appear together — the lab score is the only
        ranking that counts, regardless of where an idea originated.
      </p>

      <div className="legend">
        <span className="badge native">Native · lab walk-forward</span>
        <span className="badge ext">External seed · re-scored by Aether</span>
        <span className="badge" style={{ color: "var(--text-muted)" }}>
          {extCount} external seed{extCount === 1 ? "" : "s"} loaded
        </span>
      </div>

      {classes.length === 0 ? (
        <p className="muted">No scored strategies yet. Run backtests and imports first.</p>
      ) : (
        classes.map((cls) => (
          <div key={cls} style={{ marginBottom: 28 }}>
            <h2 className="mono" style={{ textTransform: "uppercase", color: "var(--accent-2)" }}>{cls}</h2>
            <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>strategy</th><th>symbol</th><th>score</th>
                    <th>robustness</th><th>oos</th><th>type</th>
                  </tr>
                </thead>
                <tbody>
                  {matrix[cls].map((r: any, i: number) => (
                    <tr key={i}>
                      <td style={{ color: "var(--text-primary)", fontWeight: 500 }}>{r.strategy}</td>
                      <td className="mono">{r.pair}</td>
                      <td className="num"><strong>{r.score?.toFixed?.(1)}</strong></td>
                      <td className="num">{r.robustness?.toFixed?.(3)}</td>
                      <td className="num">{r.oos_return?.toFixed?.(3)}</td>
                      <td>
                        {r.is_external ? (
                          <span className="badge ext" title="Re-scored under Aether's spread/slippage/robustness rules">
                            ext · {r.source}
                            {r.re_costed_return != null ? ` · ${r.re_costed_return.toFixed(3)}` : ""}
                          </span>
                        ) : (
                          <span className="badge native">native</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
