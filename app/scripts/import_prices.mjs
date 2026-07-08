// scripts/import_prices.mjs — import a CSV of OHLCV into PriceCandle.
// Usage: node scripts/import_prices.mjs <csv_path> <pair> [timeframe] [--demo]
import db, { log } from "./db.mjs";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { parse } from "csv-parse/sync";

const __dirname = dirname(fileURLToPath(import.meta.url));
const [csvPath, pair, timeframe = "1d", demoFlag] = process.argv.slice(2);
const isDemo = demoFlag === "--demo";
if (!csvPath || !pair) {
  log("[import:prices] usage: node import_prices.mjs <csv> <pair> [timeframe] [--demo]");
  process.exit(1);
}
const rows = parse(readFileSync(csvPath), { columns: true, skip_empty_lines: true });
const ins = db.prepare(`INSERT OR IGNORE INTO PriceCandle
  (pair,timeframe,timestamp,open,high,low,close,volume,is_demo) VALUES (?,?,?,?,?,?,?,?,?)`);
let n = 0;
for (const r of rows) {
  ins.run(pair, timeframe, r.timestamp, +r.open, +r.high, +r.low, +r.close, +r.volume, isDemo ? 1 : 0);
  n++;
}
log(`[import:prices] imported ${n} candles for ${pair} (is_demo=${isDemo})`);
db.close();
