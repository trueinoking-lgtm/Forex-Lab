// scripts/score_strategies.mjs — load engine backtest JSON into SQLite.
import db, { log } from "./db.mjs";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = join(__dirname, "..", "..", "engine", "results");

const insRun = db.prepare(`INSERT INTO BacktestRun
  (strategy,pair,timeframe,generated_at,oos_return,in_sample_return,bh_oos_return,
   sharpe,max_drawdown,profit_factor,win_rate,trade_count,beats_bh,is_demo)
  VALUES (@strategy,@pair,@timeframe,@generated_at,@oos_return,@in_sample_return,
   @bh_oos_return,@sharpe,@max_drawdown,@profit_factor,@win_rate,@trade_count,@beats_bh,0)`);
const insScore = db.prepare(`INSERT INTO StrategyScore
  (run_id,strategy,pair,score,robustness,oos_gap,share_positive_windows)
  VALUES (?,?,?,?,?,?,?)`);
const insStrategy = db.prepare(`INSERT OR IGNORE INTO Strategy (name,description,params)
  VALUES (?,?,?)`);

const files = readdirSync(resultsDir).filter((f) => f.startsWith("backtest_") && f.endsWith(".json"));
let count = 0;
for (const f of files) {
  const data = JSON.parse(readFileSync(join(resultsDir, f), "utf8"));
  for (const r of data.results) {
    insStrategy.run(r.strategy, "auto", JSON.stringify({}));
    const info = insRun.run({
      strategy: r.strategy, pair: r.pair, timeframe: data.timeframe,
      generated_at: data.generated_at, oos_return: r.oos_return,
      in_sample_return: r.in_sample_return, bh_oos_return: data.bh_oos_return,
      sharpe: r.sharpe, max_drawdown: r.max_drawdown, profit_factor: r.profit_factor,
      win_rate: r.win_rate, trade_count: r.trade_count, beats_bh: r.beats_bh ? 1 : 0,
    });
    insScore.run(info.lastInsertRowid, r.strategy, r.pair, r.score, r.robustness, r.oos_gap, r.share_positive_windows);
    count++;
  }
}
log(`[score:strategies] imported ${count} strategy scores from ${files.length} file(s)`);
db.close();
