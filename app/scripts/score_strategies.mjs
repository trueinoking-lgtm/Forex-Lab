// scripts/score_strategies.mjs — load engine backtest JSON into SQLite.
// Idempotent per (strategy, pair, run_date): re-running the daily loop replaces
// the day's run instead of appending duplicates.
import db, { log } from "./db.mjs";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = join(__dirname, "..", "..", "engine", "results");
const runDate = new Date().toISOString().slice(0, 10);

// runs upsert by (strategy, pair, run_date)
const upsertRun = db.prepare(`INSERT INTO BacktestRun
  (strategy,pair,timeframe,run_date,generated_at,oos_return,in_sample_return,bh_oos_return,
   sharpe,max_drawdown,profit_factor,win_rate,trade_count,beats_bh,is_demo,
   asset_class,is_external,source)
  VALUES (@strategy,@pair,@timeframe,@run_date,@generated_at,@oos_return,@in_sample_return,
   @bh_oos_return,@sharpe,@max_drawdown,@profit_factor,@win_rate,@trade_count,@beats_bh,0,
   @asset_class,0,NULL)
  ON CONFLICT(strategy,pair,run_date) DO UPDATE SET
   timeframe=excluded.timeframe, generated_at=excluded.generated_at,
   oos_return=excluded.oos_return, in_sample_return=excluded.in_sample_return,
   bh_oos_return=excluded.bh_oos_return, sharpe=excluded.sharpe,
   max_drawdown=excluded.max_drawdown, profit_factor=excluded.profit_factor,
   win_rate=excluded.win_rate, trade_count=excluded.trade_count,
   beats_bh=excluded.beats_bh, asset_class=excluded.asset_class`);
const delScore = db.prepare(`DELETE FROM StrategyScore WHERE run_id=?`);
const insScore = db.prepare(`INSERT INTO StrategyScore
  (run_id,strategy,pair,score,robustness,oos_gap,share_positive_windows)
  VALUES (?,?,?,?,?,?,?)`);
const insStrategy = db.prepare(`INSERT OR IGNORE INTO Strategy (name,description,params)
  VALUES (?,?,?)`);
const assetClassFor = db.prepare(`SELECT asset_class FROM Market WHERE symbol=?`);
const runIdFor = db.prepare(`SELECT id FROM BacktestRun WHERE strategy=? AND pair=? AND run_date=?`);
// yfinance uses "EURUSD=X"; our Market table stores canonical "EURUSD".
// Normalize so BacktestRun.pair joins Market + Market Profile correctly.
function canonicalPair(p) {
  return String(p).replace(/=X$/, "").replace(/=C$/, "").replace(/-USD$/, "USD").toUpperCase();
}
const files = readdirSync(resultsDir).filter((f) => f.startsWith("backtest_") && f.endsWith(".json"));
let count = 0;
const tx = db.transaction(() => {
  for (const f of files) {
    const data = JSON.parse(readFileSync(join(resultsDir, f), "utf8"));
    for (const r of data.results) {
      insStrategy.run(r.strategy, "auto", JSON.stringify({}));
      const pair = canonicalPair(r.pair);
      const ac = assetClassFor.get(pair);
      const info = upsertRun.run({
        strategy: r.strategy, pair, timeframe: data.timeframe, run_date: runDate,
        generated_at: data.generated_at, oos_return: r.oos_return,
        in_sample_return: r.in_sample_return, bh_oos_return: data.bh_oos_return,
        sharpe: r.sharpe, max_drawdown: r.max_drawdown, profit_factor: r.profit_factor,
        win_rate: r.win_rate, trade_count: r.trade_count, beats_bh: r.beats_bh ? 1 : 0,
        asset_class: ac ? ac.asset_class : "forex",
      });
      const runId = runIdFor.get(r.strategy, pair, runDate).id;
      delScore.run(runId);
      insScore.run(runId, r.strategy, pair, r.score, r.robustness, r.oos_gap, r.share_positive_windows);
      count++;
    }
  }
});
tx();
log(`[score:strategies] imported ${count} strategy scores from ${files.length} file(s)`);
db.close();
