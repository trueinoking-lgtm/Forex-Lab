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
const summary = lines.join("\n");
db.prepare(`INSERT OR REPLACE INTO DailyReport (date,summary,generated_at) VALUES (?,?,?)`)
  .run(today, summary, new Date().toISOString());
log(`[report:daily] wrote report for ${today} (${top.length} ranked)`);
// Optionally deliver to Telegram #reports via Hermes cron (out of scope here).
