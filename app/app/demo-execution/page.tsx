import {
  executionControl, demoOrders, openDemoPositions, rejectedDemoOrders,
  spreadAtEntryRows, executionJournals, paperVsDemo, lifecycleStats, lifecycleJournalRows,
} from "@/lib/db";
export const dynamic = "force-dynamic";

const STATUS_CLASS: Record<string, string> = {
  filled: "ok", rejected: "warn", pending: "native", closed: "native", skipped: "ext",
};

export default function DemoExecutionPage() {
  const ctrl = executionControl();
  const orders = demoOrders(100);
  const open = openDemoPositions();
  const rejected = rejectedDemoOrders();
  const spread = spreadAtEntryRows();
  const journals = executionJournals(50);
  const pv = paperVsDemo();
  const stats = lifecycleStats();
  const lc = lifecycleJournalRows(50);

  const killOn = ctrl.kill_switch === 1;

  return (
    <div className="animate-in">
      <h1>Demo Execution Bridge</h1>
      <p className="lead">
        Forward-test paper signals against a <strong>demo</strong> execution environment to
        learn how real fills, spreads, slippage, and rejections differ from the paper model.
        This is research-only — no live trading, no real money.
      </p>
      <p className="muted" style={{ color: "var(--warning)", fontSize: 13 }}>
        Demo only · broker_mode is hard-locked to <strong>demo</strong> · ALLOW_LIVE_ORDERS=false.
        Every order requires a stop-loss and take-profit and passes the deterministic risk engine.
        Broker secrets are read from environment variables and never stored.
      </p>

      <div className="surface-grid" style={{ marginTop: 18 }}>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Broker mode</h3>
          <span className="badge ok">{ctrl.broker_mode}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Kill switch</h3>
          <span className={`badge ${killOn ? "warn" : "ok"}`}>{killOn ? "ENGAGED" : "armed-off"}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Open demo trades</h3>
          <span className="num" style={{ fontSize: 22 }}>{open.length}</span>
          <span className="muted"> / cap {ctrl.max_open_demo_trades}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Rejected</h3>
          <span className="num" style={{ fontSize: 22 }}>{rejected.length}</span>
        </div>
      </div>

      <div className="legend" style={{ marginTop: 18 }}>
        <span className="badge ok">filled</span>
        <span className="badge warn">rejected</span>
        <span className="badge native">pending / closed</span>
        <span className="badge ext">skipped</span>
      </div>

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Open demo positions</h2>
      {open.length === 0 ? (
        <p className="muted">No open demo positions. Run <code>npm run execution:demo-order -- --signal-id N</code> with a paper signal id.</p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead>
              <tr><th>id</th><th>symbol</th><th>side</th><th>filled</th><th>SL</th><th>TP</th><th>spread</th><th>slippage</th></tr>
            </thead>
            <tbody>
              {open.map((o: any) => (
                <tr key={o.id}>
                  <td className="mono">{o.id}</td>
                  <td style={{ color: "var(--text-primary)", fontWeight: 500 }}>{o.symbol}</td>
                  <td>{o.side}</td>
                  <td className="mono">{o.filled_entry}</td>
                  <td className="mono">{o.stop_loss}</td>
                  <td className="mono">{o.take_profit}</td>
                  <td className="num">{o.spread_at_entry}</td>
                  <td className="num">{o.slippage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Rejected orders</h2>
      {rejected.length === 0 ? (
        <p className="muted">No rejected orders.</p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead>
              <tr><th>id</th><th>symbol</th><th>side</th><th>requested</th><th>reason</th></tr>
            </thead>
            <tbody>
              {rejected.map((r: any) => (
                <tr key={r.id}>
                  <td className="mono">{r.id}</td>
                  <td>{r.symbol}</td>
                  <td>{r.side}</td>
                  <td className="mono">{r.requested_entry}</td>
                  <td style={{ fontSize: 13, color: "var(--warning)" }}>{r.rejection_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Spread at entry</h2>
      {spread.length === 0 ? (
        <p className="muted">No filled orders yet to show spread/slippage.</p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead>
              <tr><th>id</th><th>symbol</th><th>side</th><th>requested</th><th>filled</th><th>spread</th><th>slippage</th></tr>
            </thead>
            <tbody>
              {spread.map((s: any) => (
                <tr key={s.id}>
                  <td className="mono">{s.id}</td>
                  <td>{s.symbol}</td>
                  <td>{s.side}</td>
                  <td className="mono">{s.requested_entry}</td>
                  <td className="mono">{s.filled_entry}</td>
                  <td className="num">{s.spread_at_entry}</td>
                  <td className="num">{s.slippage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Paper vs demo PnL</h2>
      {pv.length === 0 ? (
        <p className="muted">No execution journals yet. After a demo order is filled and reviewed, expected (paper) vs actual (demo) PnL appears here.</p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead>
              <tr><th>id</th><th>symbol</th><th>side</th><th>paper pnl</th><th>demo pnl</th><th>slippage</th><th>spread</th><th>acceptable</th></tr>
            </thead>
            <tbody>
              {pv.map((r: any) => (
                <tr key={r.id}>
                  <td className="mono">{r.demo_order_id}</td>
                  <td>{r.symbol}</td>
                  <td>{r.side}</td>
                  <td className="num">{r.expected_paper_pnl}</td>
                  <td className="num">{r.actual_demo_pnl}</td>
                  <td className="num">{r.slippage}</td>
                  <td className="num">{r.spread}</td>
                  <td>
                    {r.was_execution_acceptable == null
                      ? <span className="badge native">pending</span>
                      : r.was_execution_acceptable
                        ? <span className="badge ok">yes</span>
                        : <span className="badge warn">no</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Completed demo lifecycle checks</h2>
      <p className="muted" style={{ fontSize: 13, color: "var(--warning)" }}>
        Lifecycle runs are simulated with the <strong>mock</strong> adapter. Mock fills are
        NOT real broker fills — they estimate spread/slippage/latency so paper and demo
        models can be compared, not to represent a live venue.
      </p>
      <div className="surface-grid" style={{ marginTop: 12 }}>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Execution quality</h3>
          <span className={`badge ${stats.completed > 0 ? "ok" : "native"}`}>
            {stats.completed > 0 ? "verified" : "no completed run"}
          </span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Paper vs demo PnL delta</h3>
          <span className="num" style={{ fontSize: 22 }}>
            {stats.completed > 0
              ? (pv.reduce((a: number, r: any) => a + ((r.actual_demo_pnl || 0) - (r.expected_paper_pnl || 0)), 0) / stats.completed).toFixed(4)
              : "—"}
          </span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Avg slippage</h3>
          <span className="num" style={{ fontSize: 22 }}>{stats.avg_slippage == null ? "—" : stats.avg_slippage.toFixed(5)}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Avg spread</h3>
          <span className="num" style={{ fontSize: 22 }}>{stats.avg_spread == null ? "—" : stats.avg_spread.toFixed(5)}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Order rejections</h3>
          <span className={`num ${stats.rejections > 0 ? "" : ""}`} style={{ fontSize: 22 }}>{stats.rejections}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Worst slippage</h3>
          <span className="num" style={{ fontSize: 22 }}>{stats.worst_slippage == null ? "—" : stats.worst_slippage.toFixed(5)}</span>
        </div>
      </div>

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Lifecycle journal (mock only)</h2>
      {stats.mock_completed === 0 ? (
        <p className="muted">No completed lifecycle runs yet. Run <code>npm run execution:mock-lifecycle -- --signal-id N</code>.</p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead>
              <tr><th>run</th><th>broker</th><th>mode</th><th>symbol</th><th>paper pnl</th><th>demo pnl</th><th>delta</th><th>slippage</th><th>spread</th><th>latency</th><th>quality</th></tr>
            </thead>
            <tbody>
              {lc.map((r: any) => {
                const delta = (r.actual_demo_pnl || 0) - (r.expected_paper_pnl || 0);
                return (
                  <tr key={r.id}>
                    <td className="mono">{r.run_id}</td>
                    <td><span className="badge native">{r.broker}</span></td>
                    <td><span className="badge ok">{r.broker_mode}</span></td>
                    <td>{r.symbol}</td>
                    <td className="num">{r.expected_paper_pnl}</td>
                    <td className="num">{r.actual_demo_pnl}</td>
                    <td className="num">{delta.toFixed(4)}</td>
                    <td className="num">{r.slippage}</td>
                    <td className="num">{r.spread}</td>
                    <td className="num">{r.latency_ms}ms</td>
                    <td>
                      {r.was_execution_acceptable == null
                        ? <span className="badge native">pending</span>
                        : r.was_execution_acceptable
                          ? <span className="badge ok">ok</span>
                          : <span className="badge warn">drift</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>All demo orders</h2>
      <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
        <table className="data">
          <thead>
            <tr><th>id</th><th>signal</th><th>broker</th><th>symbol</th><th>side</th><th>status</th><th>requested</th></tr>
          </thead>
          <tbody>
            {orders.map((o: any) => (
              <tr key={o.id}>
                <td className="mono">{o.id}</td>
                <td className="mono">{o.signal_id}</td>
                <td>{o.broker}</td>
                <td>{o.symbol}</td>
                <td>{o.side}</td>
                <td><span className={`badge ${STATUS_CLASS[o.status] || "native"}`}>{o.status}</span></td>
                <td className="muted">{o.requested_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
