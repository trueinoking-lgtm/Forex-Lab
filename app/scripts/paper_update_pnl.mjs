// scripts/paper_update_pnl.mjs — snapshot account PnL for open paper trades.
// SL/TP are checked against the latest close from the engine results.
import db, { log } from "./db.mjs";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = join(__dirname, "..", "..", "engine", "results");

const account0 = 10000.0;
const openTrades = db.prepare(`SELECT * FROM PaperTrade WHERE status='open'`).all();
let equity = account0;
let openRisk = 0;
let daily = 0;
for (const t of openTrades) {
  const f = `signals_${t.pair.replace("/", "")}.json`;
  let lastClose = t.entry;
  try {
    const sig = JSON.parse(readFileSync(join(resultsDir, f), "utf8"));
    lastClose = sig.close;
  } catch { /* keep entry as fallback; real data only */ }
  const move = (lastClose - t.entry) * t.direction;
  const risk = Math.abs(t.entry - t.stop_loss) * t.direction;
  const pnl = move; // per-unit; account-scaled omitted for clarity (units tracked separately)
  equity += pnl;
  openRisk += Math.abs(risk);
  // mark exit if SL/TP hit
  let exit = null;
  if (t.direction > 0 && (lastClose <= t.stop_loss || lastClose >= t.take_profit)) exit = lastClose;
  if (t.direction < 0 && (lastClose >= t.stop_loss || lastClose <= t.take_profit)) exit = lastClose;
  if (exit) {
    db.prepare(`UPDATE PaperTrade SET status='closed', exit_price=?, exit_at=?, pnl=? WHERE id=?`)
      .run(exit, new Date().toISOString(), pnl, t.id);
    log(`[paper:update-pnl] trade ${t.id} CLOSED @ ${exit} pnl=${pnl.toFixed(4)}`);
  }
}
const ins = db.prepare(`INSERT INTO PnlSnapshot (ts,account,open_risk,daily_pnl,equity)
  VALUES (?,?,?,?,?)`);
ins.run(new Date().toISOString(), account0, openRisk, daily, equity);
log(`[paper:update-pnl] open_trades=${openTrades.length} equity=${equity.toFixed(2)} open_risk=${openRisk.toFixed(4)}`);
db.close();
