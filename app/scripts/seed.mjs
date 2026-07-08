// scripts/seed.mjs — seed demo (clearly labeled) candles + strategies + a rule.
import db, { log } from "./db.mjs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
// demo candles (label is_demo=1) — clearly NOT real market data
const insC = db.prepare(`INSERT OR IGNORE INTO PriceCandle
  (pair,timeframe,timestamp,open,high,low,close,volume,is_demo) VALUES (?,?,?,?,?,?,?,?,1)`);
const start = new Date("2024-01-01T00:00:00Z");
let p = 1.10;
for (let i = 0; i < 250; i++) {
  const ts = new Date(start.getTime() + i * 86400000).toISOString();
  const o = p; const c = p * (1 + (Math.sin(i / 10) * 0.002));
  const hi = Math.max(o, c) * 1.001; const lo = Math.min(o, c) * 0.999;
  insC.run("DEMO_EURUSD=X", "1d", ts, +o.toFixed(5), +hi.toFixed(5), +lo.toFixed(5), +c.toFixed(5), 1000);
  p = c;
}
const insS = db.prepare(`INSERT OR IGNORE INTO Strategy (name,description,params) VALUES (?,?,?)`);
for (const nm of ["ema_crossover", "ema_trend_pullback", "rsi_mean_reversion",
                  "macd_trend_confirmation", "london_breakout"]) {
  insS.run(nm, "seeded", JSON.stringify({}));
}
db.prepare(`INSERT OR IGNORE INTO RuleSet (name,current_version,body) VALUES (?,1,?)`)
  .run("min_signal_score", "40");
log("[seed] demo candles + 5 strategies + 1 rule seeded (is_demo=1 — NOT real data)");
db.close();
