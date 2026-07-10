// scripts/report_daily.mjs — build + store end-of-day report; also emit Telegram.
import db, { log } from "./db.mjs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { execSync } from "child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const cfg = (() => { try { return JSON.parse(readFileSync(join(__dirname, "..", "..", "engine", "config.yaml.telegram"), "utf8")); } catch { return null; } })();

const today = new Date().toISOString().slice(0, 10);
const top = db.prepare(`SELECT s.*, r.score, r.robustness FROM BacktestRun s
  JOIN StrategyScore r ON r.run_id = s.id
  ORDER BY r.score DESC LIMIT 5`).all();
const open = db.prepare(`SELECT COUNT(*) c FROM PaperTrade WHERE status='open'`).get();
const sigs = db.prepare(`SELECT COUNT(*) c FROM Signal WHERE status='paper'`).get();

const lines = [
  `## Aether Forex Lab — Daily Report ${today}`,
  "",
  `Open paper trades: ${open.c}`,
  `Paper signals today: ${sigs.c}`,
  "",
  `### Top strategies (OOS, scored)`,
  `| strategy | pair | score | oos | sharpe | DD | robust |`,
  `| --- | --- | --- | --- | --- | --- | --- |`,
];
for (const r of top) {
  lines.push(`| ${r.strategy} | ${r.pair} | ${r.score} | ${r.oos_return} | ${r.sharpe} | ${r.max_drawdown} | ${r.robustness} |`);
}

// ===== Demo execution quality (v1.3.1) =====
// Separated: mock execution quality vs real broker demo execution quality, so the
// report never implies mock fills are live broker fills.
const ctrl = db.prepare(`SELECT * FROM ExecutionControl WHERE id=1`).get();
const execRows = db.prepare(`
  SELECT broker, broker_mode, COUNT(*) c, AVG(slippage) avg_slip, AVG(spread) avg_spr,
         MAX(slippage) worst_slip,
         SUM(CASE WHEN actual_demo_pnl IS NOT NULL THEN 1 ELSE 0 END) done
  FROM ExecutionJournal GROUP BY broker, broker_mode
`).all();
const rej = db.prepare(`SELECT COUNT(*) c FROM DemoExecutionOrder WHERE status='rejected'`).get();
lines.push("", "### Demo execution quality",
  `- broker_mode in use: ${ctrl.broker_mode} (kill-switch: ${ctrl.kill_switch ? "ENGAGED" : "off"})`,
  `- order rejections (total): ${rej.c}`,
  `- mock vs real broker demo separated below:`);
if (execRows.length === 0) {
  lines.push("| broker | mode | runs | avg_slip | avg_spr | worst_slip |",
             "| --- | --- | --- | --- | --- | --- |",
             "| (none yet) | demo | 0 | — | — | — |");
} else {
  lines.push("| broker | mode | runs | avg_slip | avg_spr | worst_slip |",
             "| --- | --- | --- | --- | --- | --- |");
  for (const e of execRows) {
    const kind = e.broker === "mock" ? "MOCK (simulated, not a real venue)" : "REAL DEMO BROKER";
    lines.push(`| ${e.broker} (${kind}) | ${e.broker_mode} | ${e.done} | ${e.avg_slip ?? "—"} | ${e.avg_spr ?? "—"} | ${e.worst_slip ?? "—"} |`);
  }
}
// paper-vs-demo mismatch + worst slippage (mock block)
const mockAgg = db.prepare(`
  SELECT AVG(actual_demo_pnl - expected_paper_pnl) avg_delta, MAX(slippage) worst_slip
  FROM ExecutionJournal WHERE broker='mock' AND actual_demo_pnl IS NOT NULL
`).get();
lines.push("",
  `- mock paper-vs-demo avg PnL mismatch: ${mockAgg.avg_delta == null ? "—" : mockAgg.avg_delta.toFixed(4)}`,
  `- mock worst slippage: ${mockAgg.worst_slip == null ? "—" : mockAgg.worst_slip}`);

const summary = lines.join("\n");
db.prepare(`INSERT OR REPLACE INTO DailyReport (date,summary,generated_at) VALUES (?,?,?)`)
  .run(today, summary, new Date().toISOString());
log(`[report:daily] wrote report for ${today} (${top.length} ranked)`);
// Optionally deliver to Telegram #reports via Hermes cron (out of scope here).
