// scripts/review_outcomes.mjs — review open paper trades at 1h/4h/24h/final.
// Idempotent per (trade, horizon, day): re-running the daily loop overwrites
// the day's reviews instead of appending 4 rows every time.
import db, { log } from "./db.mjs";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = join(__dirname, "..", "..", "engine", "results");
const today = new Date().toISOString().slice(0, 10);

const upsert = db.prepare(`INSERT INTO OutcomeReview
  (paper_trade_id, reviewed_at, review_date, horizon, price_at_review, outcome, note)
  VALUES (?,?,?,?,?,?,'auto review')
  ON CONFLICT(paper_trade_id, horizon, review_date) DO UPDATE SET
   reviewed_at=excluded.reviewed_at, price_at_review=excluded.price_at_review,
   outcome=excluded.outcome`);

const open = db.prepare(`SELECT * FROM PaperTrade WHERE status='open'`).all();
for (const t of open) {
  const f = `signals_${t.pair.replace("/", "")}.json`;
  let price = t.entry;
  try { price = JSON.parse(readFileSync(join(resultsDir, f), "utf8")).close; } catch {}
  const outcome = price > t.entry ? "win" : "loss";
  for (const horizon of ["1h", "4h", "24h", "final"]) {
    upsert.run(t.id, new Date().toISOString(), today, horizon, price, outcome);
  }
  log(`[review:outcomes] trade ${t.id} ${t.strategy} @${price} -> ${outcome}`);
}
db.close();
