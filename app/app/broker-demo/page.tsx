import {
  executionControl, latestBrokerCaps, openDemoPositionsByBroker, brokerSpreadComparison,
  paperVsBrokerPnl, brokerLatency, realDemoOrders, rejectedDemoOrders,
  remoteBridgeStatus, openDemoPositions,
} from "@/lib/db";
export const dynamic = "force-dynamic";

const BROKER_LABEL: Record<string, string> = {
  mock: "MOCK (simulated)",
  oanda_practice: "OANDA Practice",
  mt5_demo: "MT5 demo",
};

export default function BrokerDemoPage() {
  const ctrl = executionControl();
  const caps = latestBrokerCaps();
  const openByBroker = openDemoPositionsByBroker();
  const spreads = brokerSpreadComparison();
  const latency = brokerLatency();
  const rejected = rejectedDemoOrders();
  const realOrders = realDemoOrders();
  const bridge = remoteBridgeStatus();
  const openRemotePositions = openDemoPositions().filter((o: any) => o.broker === "remote_mt5");

  const killOn = ctrl.kill_switch === 1;
  const capMap = Object.fromEntries(caps.map((c: any) => [c.broker, c]));

  // Execution quality scoring per real broker (lower avg slippage + spread => better).
  const quality: Record<string, number | null> = {};
  for (const s of spreads) {
    const cur = quality[s.broker] ?? 0;
    quality[s.broker] = cur + ((s.avg_slip || 0) + (s.avg_spread || 0));
  }
  const realBrokers = Object.keys(quality);
  const winner = realBrokers.length
    ? realBrokers.reduce((a, b) => (quality[a]! <= quality[b]! ? a : b))
    : null;

  return (
    <div className="animate-in">
      <h1>Broker Demo Forward-Testing</h1>
      <p className="lead">
        Run paper signals through <strong>real demo broker</strong> accounts (OANDA Practice,
        MT5 demo) to compare fills, spreads, slippage, and latency against the paper model.
      </p>
      <p className="muted" style={{ color: "var(--warning)", fontSize: 13 }}>
        <strong>NEVER LIVE.</strong> broker_mode is hard-locked to <strong>demo</strong> ·
        ALLOW_LIVE_ORDERS=false · Kill switch blocks all broker demo execution. Broker secrets
        come from environment variables only and are redacted everywhere. Any "REAL DEMO BROKER"
        row is a practice/sandbox account — never a live venue.
      </p>

      <div className="surface-grid" style={{ marginTop: 18 }}>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Execution mode</h3>
          <span className={`badge ${(ctrl as any).execution_mode === "observe_only" ? "native" : "ext"}`}>
            {(ctrl as any).execution_mode}
          </span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Kill switch</h3>
          <span className={`badge ${killOn ? "warn" : "ok"}`}>{killOn ? "ENGAGED" : "armed-off"}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>DRY_RUN</h3>
          <span className="badge native">on by default</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Primary demo broker</h3>
          <span className="badge ext">{(ctrl as any).primary_demo_broker}</span>
        </div>
      </div>

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Broker readiness</h2>
      <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
        <table className="data">
          <thead>
            <tr><th>broker</th><th>mode</th><th>creds present</th><th>account reachable</th><th>currency</th><th>balance</th><th>trading</th><th>last checked</th><th>error</th></tr>
          </thead>
          <tbody>
            {caps.map((c: any) => (
              <tr key={c.broker}>
                <td style={{ fontWeight: 500 }}>{BROKER_LABEL[c.broker] || c.broker}</td>
                <td><span className="badge ok">{c.broker_mode}</span></td>
                <td><span className={`badge ${c.credentials_present ? "ok" : "warn"}`}>{c.credentials_present ? "yes" : "no"}</span></td>
                <td><span className={`badge ${c.account_reachable ? "ok" : "native"}`}>{c.account_reachable ? "yes" : "no"}</span></td>
                <td className="mono">{c.account_currency || "—"}</td>
                <td className="num">{c.balance == null ? "—" : c.balance}</td>
                <td><span className={`badge ${c.trading_enabled ? "ok" : "native"}`}>{c.trading_enabled ? "on" : "off"}</span></td>
                <td className="muted">{c.last_checked_at}</td>
                <td style={{ fontSize: 12, color: "var(--warning)" }}>{c.last_error_redacted || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Open demo trades by broker</h2>
      <div className="surface-grid">
        {openByBroker.length === 0 ? (
          <div className="surface-card"><span className="muted">No open demo trades.</span></div>
        ) : openByBroker.map((r: any) => (
          <div className="surface-card" key={r.broker}>
            <h3 style={{ color: "var(--accent-2)" }}>{BROKER_LABEL[r.broker] || r.broker}</h3>
            <span className="num" style={{ fontSize: 22 }}>{r.c}</span>
          </div>
        ))}
      </div>

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Broker spread &amp; slippage comparison</h2>
      {spreads.length === 0 ? (
        <p className="muted">No filled broker orders yet. Run <code>npm run execution:broker-check</code> then a dry-run to populate comparisons.</p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead>
              <tr><th>broker</th><th>symbol</th><th>avg spread</th><th>avg slippage</th><th>n</th></tr>
            </thead>
            <tbody>
              {spreads.map((s: any, i: number) => (
                <tr key={i}>
                  <td>{BROKER_LABEL[s.broker] || s.broker}</td>
                  <td>{s.symbol}</td>
                  <td className="num">{s.avg_spread == null ? "—" : Number(s.avg_spread).toFixed(5)}</td>
                  <td className="num">{s.avg_slip == null ? "—" : Number(s.avg_slip).toFixed(5)}</td>
                  <td className="num">{s.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Broker latency</h2>
      <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
        <table className="data">
          <thead><tr><th>broker</th><th>avg latency ms</th><th>n</th></tr></thead>
          <tbody>
            {latency.length === 0 ? (
              <tr><td colSpan={3} className="muted">No latency data yet.</td></tr>
            ) : latency.map((l: any) => (
              <tr key={l.broker}>
                <td>{BROKER_LABEL[l.broker] || l.broker}</td>
                <td className="num">{l.avg_latency_ms == null ? "—" : Number(l.avg_latency_ms).toFixed(2)}</td>
                <td className="num">{l.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Paper vs OANDA demo PnL</h2>
      <BrokerPnlTable broker="oanda_practice" rows={paperVsBrokerPnl("oanda_practice")} label="OANDA Practice" />

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Paper vs MT5 demo PnL</h2>
      <BrokerPnlTable broker="mt5_demo" rows={paperVsBrokerPnl("mt5_demo")} label="MT5 demo" />

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>OANDA vs MT5 slippage comparison</h2>
      {realBrokers.length < 2 ? (
        <p className="muted">Need at least one completed run on both OANDA and MT5 to compare slippage. Both require credentials + DRY_RUN=false + DEMO_AUTOTRADE_ENABLED=true.</p>
      ) : (
        <div className="surface-grid">
          {realBrokers.map((b) => (
            <div className="surface-card" key={b}>
              <h3 style={{ color: "var(--accent-2)" }}>{BROKER_LABEL[b] || b}</h3>
              <span className="muted">avg (slippage+spread) {Number(quality[b]).toFixed(5)}</span>
            </div>
          ))}
        </div>
      )}

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Real demo broker orders</h2>
      <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
        <table className="data">
          <thead><tr><th>id</th><th>signal</th><th>broker</th><th>symbol</th><th>side</th><th>status</th><th>requested</th></tr></thead>
          <tbody>
            {realOrders.length === 0 ? (
              <tr><td colSpan={7} className="muted">No real demo broker orders placed yet.</td></tr>
            ) : realOrders.map((o: any) => (
              <tr key={o.id}>
                <td className="mono">{o.id}</td>
                <td className="mono">{o.signal_id}</td>
                <td>{BROKER_LABEL[o.broker] || o.broker}</td>
                <td>{o.symbol}</td>
                <td>{o.side}</td>
                <td><span className="badge native">{(o as any).status}</span></td>
                <td className="muted">{o.requested_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Rejected demo orders</h2>
      {rejected.length === 0 ? (
        <p className="muted">No rejected orders.</p>
      ) : (
        <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data">
            <thead><tr><th>id</th><th>broker</th><th>symbol</th><th>side</th><th>requested</th><th>reason</th></tr></thead>
            <tbody>
              {rejected.map((r: any) => (
                <tr key={r.id}>
                  <td className="mono">{r.id}</td>
                  <td>{BROKER_LABEL[r.broker] || r.broker}</td>
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

      <h2 style={{ color: "var(--accent-2)", marginTop: 28 }}>Remote MT5 Bridge (Tailscale → Windows PC)</h2>
      <p className="muted" style={{ fontSize: 12 }}>
        VPS holds only REMOTE_MT5_BRIDGE_URL + TOKEN. MT5 credentials stay on the PC .env.
        Demo-only; PC bridge kill-switch + VPS kill-switch both block orders.
      </p>
      <div className="surface-grid" style={{ marginTop: 14 }}>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Bridge reachable</h3>
          <span className={`badge ${bridge?.reachable ? "ok" : "warn"}`}>{bridge?.reachable ? "yes" : "no"}</span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Tailscale URL configured</h3>
          <span className={`badge ${bridge?.tailscale_url_configured ? "ok" : "native"}`}>
            {bridge?.tailscale_url_configured ? "yes" : "no"}
          </span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>PC bridge mode</h3>
          <span className={`badge ${bridge?.pc_bridge_mode === "demo" ? "ok" : "warn"}`}>
            {bridge?.pc_bridge_mode || "unknown"}
          </span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Bridge kill-switch</h3>
          <span className={`badge ${bridge?.bridge_kill_switch ? "warn" : "ok"}`}>
            {bridge?.bridge_kill_switch ? "ENGAGED" : "armed-off"}
          </span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Latest MT5 quote</h3>
          <span className="mono" style={{ fontSize: 14 }}>
            {bridge?.latest_symbol
              ? `${bridge.latest_symbol} ${bridge.latest_bid} / ${bridge.latest_ask} (spr ${bridge.latest_spread})`
              : "—"}
          </span>
        </div>
        <div className="surface-card">
          <h3 style={{ color: "var(--accent-2)" }}>Open remote positions</h3>
          <span className="num" style={{ fontSize: 22 }}>{openRemotePositions.length}</span>
        </div>
      </div>
      <div className="panel glass" style={{ padding: 16, marginTop: 14 }}>
        <h3 style={{ color: "var(--accent-2)" }}>Symbol map (PC → broker)</h3>
        {bridge?.symbol_map_json ? (
          <pre className="mono" style={{ fontSize: 12 }}>{bridge.symbol_map_json}</pre>
        ) : (
          <span className="muted">No symbol map fetched yet. Run <code>npm run execution:remote-mt5-symbols</code>.</span>
        )}
      </div>

      <p className="muted" style={{ marginTop: 24, fontSize: 12 }}>
        Broker winner today (by execution quality):{" "}
        <strong>{winner ? (BROKER_LABEL[winner] || winner) : "no real-broker data yet"}</strong>.
        All rows above for OANDA/MT5 are <strong>REAL DEMO BROKER</strong> (practice) fills — never live.
      </p>
    </div>
  );
}

function BrokerPnlTable({ broker, rows, label }: { broker: string; rows: any[]; label: string }) {
  if (rows.length === 0) {
    return <p className="muted">No {label} execution journals yet. Place a demo order via that broker to populate.</p>;
  }
  return (
    <div className="panel glass" style={{ padding: 0, overflow: "hidden" }}>
      <table className="data">
        <thead><tr><th>id</th><th>symbol</th><th>side</th><th>paper pnl</th><th>demo pnl</th><th>slippage</th><th>spread</th><th>acceptable</th></tr></thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.id}>
              <td className="mono">{r.id}</td>
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
  );
}
