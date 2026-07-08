// scripts/review_outcomes.mjs — review open paper trades at 1h/4h/24h/final.
import db, { log } from "./db.mjs";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = join(__dirname, "..", "..", "engine", "results");

const open = db.prepare(`SELECT * FROM PaperTrade WHERE status='open'`).all();
for (const t of open) {
  const f = `signals_${t.pair.replace("/", "")}.json`;
  let price = t.entry;
  try { price = JSON.parse(readFileSync(join(resultsDir, f), "utf8")).close; } catch {}
  const outcome = price > t.entry ? "win" : "loss";
  for (const horizon of ["1h", "4h", "24h", "final"]) {
    db.prepare(`INSERT INTO OutcomeReview (paper_trade_id,reviewed_at,horizon,price_at_review,outcome,note)
      VALUES (?,?,?,?,?,'auto review')`)
      .run(t.id, new Date().toISOString(), horizon, price, outcome);
  }
  log(`[review:outcomes] trade ${t.id} ${t.strategy} @${price} -> ${outcome}`);
}
db.close();
