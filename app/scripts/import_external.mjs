// scripts/import_external.mjs — import external research results and load the
// re-scored (OUR rules) output into SQLite.
//
// External platforms are IDEA SOURCES ONLY. The engine's import_external.py
// validates + labels + re-scores each strategy with OUR spread/slippage/
// walk-forward/paper rules. This script only persists the re-scored results,
// tagged is_external=1. No live execution. No broker credentials.
import db, { log } from "./db.mjs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { readFileSync } from "fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ENGINE = join(__dirname, "..", "..", "engine");
const APP = join(__dirname, "..");
const fileArg = process.argv[2];

if (!fileArg) {
  console.error("usage: node scripts/import_external.mjs <path-to-import.json|csv>");
  process.exit(1);
}

// 1) run the engine re-scorer (fail-loud; paper_only enforced in engine)
const py = join(ENGINE, ".venv", "bin", "python");
execFileSync(py, ["import_external.py", fileArg], { cwd: ENGINE, stdio: "inherit" });

// 2) load results/imports.json into ExternalImport + ImportReScore
const payload = JSON.parse(readFileSync(join(ENGINE, "results", "imports.json"), "utf8"));
const ts = new Date().toISOString();

const insImport = db.prepare(`INSERT INTO ExternalImport
  (imported_at, source_file, source, strategy_name, symbol, asset_class, trades,
   external_net_return, external_win_rate, external_profit_factor,
   external_max_drawdown, external_sharpe, external_reported_spread_bps, is_external)
  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)`);
const insReScore = db.prepare(`INSERT INTO ImportReScore
  (import_id, scored_at, strategy_label, symbol, asset_class, score, robustness,
   re_costed_return, our_cost_bps, cost_gap_bps, external_net_return)
  VALUES (?,?,?,?,?,?,?,?,?,?,?)`);

let n = 0;
for (const r of payload.results) {
  const info = insImport.run(
    ts, payload.source_file, r.source, r.strategy, r.symbol, r.asset_class, r.trade_count,
    r.external_net_return, r.win_rate, r.profit_factor, r.max_drawdown, r.sharpe,
    r.external_reported_spread_bps);
  insReScore.run(
    info.lastInsertRowid, ts, r.strategy, r.symbol, r.asset_class, r.score, r.robustness,
    r.re_costed_return, r.our_cost_bps, r.cost_gap_bps, r.external_net_return);
  n++;
}
log(`[import:external] loaded ${n} re-scored external strategies (is_external=1, paper_only=${payload.paper_only})`);
db.close();
