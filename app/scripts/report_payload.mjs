// scripts/report_payload.mjs — build the Telegram-ready daily payload.
// Reads SQLite; emits JSON (for the delivery layer) + a concise Markdown message.
// SAFETY: paper_only by construction; no live trade output ever.
import db, { log } from "./db.mjs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { writeFileSync } from "fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ENGINE = join(__dirname, "..", "..", "engine", "results");

const today = new Date().toISOString().slice(0, 10);

// --- strategy rankings (OOS, scored) ---
const ranked = db.prepare(`SELECT s.strategy, s.pair, r.score, r.robustness,
  s.oos_return, s.in_sample_return, s.bh_oos_return, s.sharpe, s.max_drawdown,
  s.profit_factor, s.win_rate, s.trade_count, s.beats_bh
  FROM BacktestRun s JOIN StrategyScore r ON r.run_id = s.id
  ORDER BY r.score DESC`).all();
const best = ranked[0] || null;
const worst = ranked[ranked.length - 1] || null;

// --- baseline comparison (regime-filtered signals vs buy & hold) ---
// beats_baseline = best strategy's OOS return > buy-and-hold OOS return
const bh = best ? best.bh_oos_return : null;
const beatsBaseline = best ? best.oos_return > (bh ?? 0) : false;

// --- paper PnL ---
const pnl = db.prepare(`SELECT * FROM PnlSnapshot ORDER BY ts DESC LIMIT 1`).get();
const openTrades = db.prepare(`SELECT * FROM PaperTrade WHERE status='open'`).all();
const closedTrades = db.prepare(`SELECT * FROM PaperTrade WHERE status='closed' ORDER BY id DESC LIMIT 20`).all();
const bestTrade = [...openTrades, ...closedTrades].reduce((a, t) => {
  const p = t.pnl ?? 0; return (a === null || p > (a.pnl ?? -1e9)) ? t : a;
}, null);
const worstTrade = [...openTrades, ...closedTrades].reduce((a, t) => {
  const p = t.pnl ?? 0; return (a === null || p < (a.pnl ?? 1e9)) ? t : a;
}, null);

// --- rule changes within the last 24h ---
const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
const ruleChanges = db.prepare(`SELECT * FROM RuleChange WHERE changed_at >= ? ORDER BY changed_at DESC`).all(since);

// --- warnings / errors from scheduler run log (last 24h) ---
const failures = db.prepare(`SELECT command, error_message, finished_at FROM SchedulerRunLog
  WHERE success = 0 AND started_at >= ? ORDER BY started_at DESC`).all(since);

// --- compose concise markdown (minimal, no spam) ---
const lines = [];
lines.push(`📊 *Aether Forex Lab — Daily (${today})*`);
lines.push("");
lines.push(`*Regime-filtered vs baseline:* ${beatsBaseline ? "✅ beat B&H" : "❌ below B&H"}`);
if (bh !== null) lines.push(`  best OOS ${best.oos_return.toFixed(4)} vs B&H ${bh.toFixed(4)}`);
lines.push("");
lines.push(`*Paper PnL:* equity ${pnl ? pnl.equity.toFixed(2) : "n/a"} · open risk ${pnl ? pnl.open_risk.toFixed(4) : "n/a"}`);
lines.push(`*Open trades:* ${openTrades.length} · *Closed (recent):* ${closedTrades.length}`);
if (bestTrade) lines.push(`*Best trade:* ${bestTrade.strategy} ${bestTrade.direction > 0 ? "L" : "S"} ${fmtPnl(bestTrade.pnl)}`);
if (worstTrade) lines.push(`*Worst trade:* ${worstTrade.strategy} ${worstTrade.direction > 0 ? "L" : "S"} ${fmtPnl(worstTrade.pnl)}`);
lines.push("");
lines.push(`*Best strategy:* ${best ? `${best.strategy} (${best.score.toFixed(1)})` : "n/a"}`);
lines.push(`*Worst strategy:* ${worst ? `${worst.strategy} (${worst.score.toFixed(1)})` : "n/a"}`);
if (ruleChanges.length) {
  lines.push("");
  lines.push(`*Rule changes (24h):* ${ruleChanges.length}`);
  for (const rc of ruleChanges.slice(0, 5)) {
    lines.push(`  • ${rc.rule} v${rc.version}: ${rc.from_value ?? "—"} → ${rc.to_value}${rc.reason ? ` (${rc.reason})` : ""}`);
  }
}
if (failures.length) {
  lines.push("");
  lines.push(`⚠️ *Warnings/errors (24h):* ${failures.length}`);
  for (const f of failures.slice(0, 3)) {
    const msg = String(f.error_message).replace(/\/root\/[^\s:]+/g, "<path>").slice(0, 120);
    lines.push(`  • ${f.command.split(":")[0]} failed: ${msg}`);
  }
}
const message = lines.join("\n");

const payload = {
  date: today,
  paper_only: true,
  beats_baseline: beatsBaseline,
  best_strategy: best ? { name: best.strategy, score: best.score, oos: best.oos_return } : null,
  worst_strategy: worst ? { name: worst.strategy, score: worst.score, oos: worst.oos_return } : null,
  baseline_bh_oos: bh,
  paper: {
    equity: pnl ? pnl.equity : null,
    open_risk: pnl ? pnl.open_risk : null,
    open_trades: openTrades.length,
    best_trade: bestTrade ? tradeBrief(bestTrade) : null,
    worst_trade: worstTrade ? tradeBrief(worstTrade) : null,
  },
  rule_changes: ruleChanges.map((r) => ({ rule: r.rule, version: r.version, from: r.from_value, to: r.to_value, reason: r.reason })),
  failures,
  message,
};

writeFileSync(join(ENGINE, "daily_report_payload.json"), JSON.stringify(payload, null, 2));
writeFileSync(join(ENGINE, "daily_report_message.md"), message);
log(`[report_payload] wrote payload + message (paper_only=${payload.paper_only}, beats_baseline=${beatsBaseline})`);
db.close();

function fmtPnl(p) { return p == null ? "n/a" : (p >= 0 ? `+${p.toFixed(4)}` : p.toFixed(4)); }
function tradeBrief(t) { return { id: t.id, strategy: t.strategy, dir: t.direction > 0 ? "L" : "S", pnl: t.pnl, status: t.status }; }
