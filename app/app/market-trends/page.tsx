import {
  latestTrendSnapshots, latestPredictionFor, trendAccuracyBy, recentTrendLessons,
} from "@/lib/db";
export const dynamic = "force-dynamic";

const DIR_CLASS: Record<string, string> = {
  bullish: "ok", bearish: "warn", sideways: "native", uncertain: "ext",
};
const REGIME_CLASS: Record<string, string> = {
  trend: "ok", range: "native", volatile: "warn", uncertain: "ext",
};

export default function MarketTrendsPage() {
  const snaps = latestTrendSnapshots();
  const accSym = trendAccuracyBy(["symbol"]);
  const accHor = trendAccuracyBy(["horizon"]);
  const lessons = recentTrendLessons(12);

  // latest prediction outcome per symbol (1d horizon as the headline)
  const outcomes = snaps.map((s: any) => {
    const p = latestPredictionFor(s.symbol, "1d");
    return { snap: s, pred: p };
  });

  return (
    <div className="animate-in">
      <h1>Market Trend Intelligence</h1>
      <p className="lead">
        Probabilistic, evidence-based trend detection across enabled forex and metal
        markets. Every read is expressed as a probability with an <strong>invalidation
        level</strong>, and every prediction is stored and later reviewed against actuals
        and three naive baselines. This is research intelligence — not a trade.
      </p>
      <p className="muted" style={{ color: "var(--warning)", fontSize: 13 }}>
        No certainty is claimed. Directions are probabilities. A prediction is invalidated
        if price touches its invalidation level. Paper-only · no live execution.
      </p>

      <div className="legend">
        <span className="badge native">sideways</span>
        <span className="badge ok">bullish / trend</span>
        <span className="badge warn">bearish / volatile</span>
        <span className="badge ext">uncertain</span>
      </div>

      {snaps.length === 0 ? (
        <p className="muted">
          No trend snapshots yet. Run <code>npm run trends:detect</code> (engine) then
          {" "}<code>npm run trends:ingest</code>.
        </p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead>
              <tr>
                <th>symbol</th><th>regime</th><th>direction</th><th>confidence</th>
                <th>trend str.</th><th>best strategy</th><th>invalidation</th>
                <th>last 1d outcome</th>
              </tr>
            </thead>
            <tbody>
              {outcomes.map(({ snap, pred }: any, i: number) => (
                <tr key={i}>
                  <td style={{ color: "var(--text-primary)", fontWeight: 500 }}>{snap.symbol}</td>
                  <td><span className={`badge ${REGIME_CLASS[snap.regime] || "native"}`}>{snap.regime}</span></td>
                  <td><span className={`badge ${DIR_CLASS[snap.direction] || "native"}`}>{snap.direction}</span></td>
                  <td className="num">{(snap.confidence_score * 100).toFixed(0)}%</td>
                  <td className="num">{snap.trend_strength?.toFixed?.(2)}</td>
                  <td>{snap.best_strategy || "—"}</td>
                  <td className="mono">{snap.invalidation_price}</td>
                  <td className="num">
                    {pred ? (
                      pred.was_correct == null
                        ? <span className="badge native">pending</span>
                        : pred.was_correct
                          ? <span className="badge ok">correct · {pred.outcome_direction}</span>
                          : <span className="badge warn">miss · {pred.outcome_direction}</span>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="surface-grid" style={{ marginTop: 28 }}>
        <div className="surface-card" style={{ gridColumn: "1 / -1" }}>
          <h2 style={{ color: "var(--accent-2)" }}>Accuracy by symbol</h2>
          <AccuracyTable rows={accSym} by="symbol" />
        </div>
        <div className="surface-card" style={{ gridColumn: "1 / -1" }}>
          <h2 style={{ color: "var(--accent-2)" }}>Accuracy by horizon</h2>
          <AccuracyTable rows={accHor} by="horizon" />
        </div>
      </div>

      {lessons.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <h2 style={{ color: "var(--accent-2)" }}>Review lessons (misses vs baselines)</h2>
          <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
            <table className="data">
              <thead>
                <tr><th>symbol</th><th>horizon</th><th>pred</th><th>actual</th><th>lost to</th><th>lesson</th></tr>
              </thead>
              <tbody>
                {lessons.map((l: any, i: number) => (
                  <tr key={i}>
                    <td className="mono">{l.symbol}</td>
                    <td>{l.horizon}</td>
                    <td>{l.predicted_direction}</td>
                    <td>{l.outcome_direction}</td>
                    <td>{l.baseline_miss || "all baselines"}</td>
                    <td style={{ fontSize: 13, color: "var(--text-secondary)" }}>{l.lesson}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function AccuracyTable({ rows, by }: { rows: any[]; by: string }) {
  if (!rows.length)
    return <p className="muted">No reviewed predictions yet — outcomes fill in after each horizon (1h/4h/1d).</p>;
  return (
    <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
      <table className="data">
        <thead>
          <tr><th>{by}</th><th>n</th><th>correct</th><th>avg conf</th><th>accuracy</th></tr>
        </thead>
        <tbody>
          {rows.map((r: any, i: number) => (
            <tr key={i}>
              <td className="mono">{r[by]}</td>
              <td className="num">{r.n}</td>
              <td className="num">{r.correct}</td>
              <td className="num">{((r.avg_confidence || 0) * 100).toFixed(0)}%</td>
              <td className="num"><strong>{r.accuracy_pct}%</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
