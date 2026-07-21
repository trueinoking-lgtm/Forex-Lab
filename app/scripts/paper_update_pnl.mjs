// scripts/paper_update_pnl.mjs — snapshot account PnL for open paper trades.
// SL/TP are checked against the latest close from the engine results.
//
// PnL is ACCOUNT-SCALED: each trade carries `units` (risk-sized position from
// risk_check). Unrealized PnL = units * (lastClose - entry) * direction.
// Open risk = units * |entry - stop_loss| (always >= 0). Equity = starting
// capital + realized closed PnL + unrealized open PnL.
import db, { log } from "./db.mjs";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = process.env.AETHER_RESULTS_DIR || join(__dirname, "..", "..", "engine", "results");

const account0 = 10000.0; // simulated starting capital (paper)

// realized PnL from already-closed trades
const closed = db.prepare(`SELECT pnl FROM PaperTrade
  WHERE status='closed' AND accounting_version=2 AND pnl IS NOT NULL`).all();
let realized = 0;
for (const c of closed) realized += (c.pnl || 0);

const openTrades = db.prepare(`SELECT * FROM PaperTrade
  WHERE status='open' AND accounting_version=2`).all();
let openPnl = 0;
let openRisk = 0;
for (const t of openTrades) {
  const f = `signals_${t.pair.replace("/", "")}.json`;
  let lastClose = t.entry;
  try {
    const sig = JSON.parse(readFileSync(join(resultsDir, f), "utf8"));
    lastClose = sig.close;
  } catch { /* keep entry as fallback; real data only */ }
  const units = t.units || 0;
  const move = (lastClose - t.entry) * t.direction * units;   // account-scaled
  const risk = Math.abs(t.entry - t.stop_loss) * units;        // >= 0, correct sign
  openPnl += move;
  openRisk += risk;
  // mark exit if SL/TP hit (use trade direction)
  let exit = null;
  if (t.direction > 0 && (lastClose <= t.stop_loss || lastClose >= t.take_profit)) exit = lastClose;
  if (t.direction < 0 && (lastClose >= t.stop_loss || lastClose <= t.take_profit)) exit = lastClose;
  if (exit) {
    const pnl = (exit - t.entry) * t.direction * units;
    db.prepare(`UPDATE PaperTrade SET status='closed', exit_price=?, exit_at=?, pnl=? WHERE id=?`)
      .run(exit, new Date().toISOString(), pnl, t.id);
    log(`[paper:update-pnl] trade ${t.id} CLOSED @ ${exit} pnl=${pnl.toFixed(2)}`);
    // move this trade's realized PnL into realized and out of open
    realized += pnl;
    openPnl -= move;
    openRisk -= risk;
  }
}
const equity = account0 + realized + openPnl;
const daily = openPnl; // session unrealized move (informational)

const now = new Date().toISOString();
const priorMax = db.prepare(`SELECT MAX(max_concurrent_risk) n FROM PaperLedgerSnapshot`).get().n || 0;
const maxConcurrentRisk = Math.max(priorMax, openTrades.length);
const legacyTrades = db.prepare(`SELECT COUNT(*) c FROM PaperTrade
  WHERE accounting_version IS NULL OR accounting_version<>2`).get().c;
const legacySnapshots = db.prepare(`SELECT COUNT(*) c FROM PnlSnapshot
  WHERE accounting_version IS NULL OR accounting_version<>2`).get().c;
const ignoredLegacyRecords = legacyTrades + legacySnapshots;
const ignoredLegacyNote = "Legacy PaperTrade/PnlSnapshot rows (accounting_version != 2) are excluded from v2 equity; max concurrent risk is the running maximum observed by ledger snapshots.";

db.prepare(`INSERT INTO PnlSnapshot
  (ts,account,open_risk,daily_pnl,equity,accounting_version) VALUES (?,?,?,?,?,2)`)
  .run(now, account0, openRisk, daily, equity);
db.prepare(`INSERT INTO PaperLedgerSnapshot
  (ts,starting_equity,current_equity,realized_pnl,unrealized_pnl,open_risk,
   max_concurrent_risk,bankrupt,accounting_version,accounting_model,
   ledger_updated_at,ignored_legacy_records,ignored_legacy_note)
  VALUES (?,?,?,?,?,?,?,?,2,'normalized_equal_risk_v1',?,?,?)`).run(
    now, account0, equity, realized, openPnl, openRisk, maxConcurrentRisk,
    equity <= 0 ? 1 : 0, now, ignoredLegacyRecords, ignoredLegacyNote);
log(`[paper:update-pnl] open=${openTrades.length} equity=${equity.toFixed(2)} ` +
    `realized=${realized.toFixed(2)} unrealized=${openPnl.toFixed(2)} open_risk=${openRisk.toFixed(2)}`);
db.close();
