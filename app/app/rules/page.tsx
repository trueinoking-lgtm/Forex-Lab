import { ruleChanges } from "@/lib/db";
export const dynamic = "force-dynamic";
export default function RulesPage() {
  const rows = ruleChanges() as any[];
  return (
    <div>
      <h1 style={{ color: "#5eead4" }}>Rules</h1>
      <p style={{ color: "#9ca3af" }}>Every rule change is versioned. Update via <code>npm run update:rules &lt;rule&gt; &lt;value&gt; [reason]</code>.</p>
      {rows.length === 0 ? <p>No rule changes yet. Try <code>npm run update:rules min_signal_score 45 "evidence: raise bar"</code>.</p> :
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}>
          <thead><tr style={{ color: "#9ca3af", textAlign: "left" }}>
            <th style={th}>rule</th><th style={th}>v</th><th style={th}>from</th><th style={th}>to</th><th style={th}>reason</th><th style={th}>when</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #1f2937" }}>
                <td style={td}>{r.rule}</td><td style={td}>v{r.version}</td>
                <td style={td}>{r.from_value ?? "—"}</td><td style={td}>{r.to_value}</td>
                <td style={td}>{r.reason}</td><td style={td}>{String(r.changed_at).slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>}
    </div>
  );
}
const th: React.CSSProperties = { padding: "8px 10px" };
const td: React.CSSProperties = { padding: "8px 10px" };
