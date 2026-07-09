import { topStrategies, paperTrades, pnlSnapshots, externalImports } from "@/lib/db";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default function OverviewPage() {
  const top = topStrategies(5);
  const trades = paperTrades();
  const pnl = pnlSnapshots();
  const ext = externalImports();
  const open = trades.filter((t: any) => t.status === "open").length;
  const best = top[0];

  return (
    <div className="animate-in">
      <h1>Multi-Market Research Hub</h1>
      <p className="lead">
        A local-first forex research and paper-trading dashboard. Walk-forward–scored
        strategies across <span className="mono">forex</span>,{" "}
        <span className="mono">metals</span> and <span className="mono">crypto</span> — with
        external ideas re-scored under our own spread, slippage and robustness rules.
        Paper-only. No live execution, ever.
      </p>

      <div className="legend">
        <span className="badge native">Native · lab walk-forward</span>
        <span className="badge ext">External seed · re-scored by Aether</span>
      </div>

      <div className="stat-grid stagger">
        <div className="stat">
          <div className="label">Top strategy</div>
          <div className="value">{best ? best.strategy : "—"}</div>
        </div>
        <div className="stat">
          <div className="label">Best OOS score</div>
          <div className="value accent">{best ? best.score.toFixed(1) : "—"}</div>
        </div>
        <div className="stat">
          <div className="label">Open paper trades</div>
          <div className="value">{String(open)}</div>
        </div>
        <div className="stat">
          <div className="label">External seeds</div>
          <div className="value">{String(ext.length)}</div>
        </div>
      </div>

      <h2 className="animate-rise">Top strategies</h2>
      <Table rows={top} />
    </div>
  );
}

function Table({ rows }: { rows: any[] }) {
  if (!rows.length)
    return (
      <p className="muted">No data yet — run <span className="mono">npm run backtest &amp;&amp; npm run score:strategies</span>.</p>
    );
  return (
    <div className="panel glass animate-rise" style={{ padding: 0, overflow: "hidden" }}>
      <table className="data">
        <thead>
          <tr>
            <th>strategy</th><th>pair</th><th>score</th>
            <th>oos</th><th>sharpe</th><th>DD</th><th>robust</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ color: "var(--text-primary)", fontWeight: 500 }}>{r.strategy}</td>
              <td className="mono">{r.pair}</td>
              <td className="num">{r.score?.toFixed?.(1)}</td>
              <td className="num">{r.oos_return?.toFixed?.(3)}</td>
              <td className="num">{r.sharpe?.toFixed?.(2)}</td>
              <td className="num">{r.max_drawdown?.toFixed?.(3)}</td>
              <td className="num">{r.robustness?.toFixed?.(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
