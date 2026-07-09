// scripts/review_trends.mjs — review Market Trend Intelligence predictions.
//
// For every prediction whose horizon has elapsed and which is not yet reviewed:
//   - fetch the current price for the symbol (from the engine's cached CSV)
//   - record outcome_price / outcome_direction / was_correct (review fields ONLY)
//   - compare the lab prediction vs three naive baselines:
//       (a) follow previous candle  (b) assume no change  (c) follow EMA trend
//   - if the lab prediction was wrong, store a TrendReviewLesson with which
//     baseline(s) it lost to and an evidence-based lesson.
//
// SAFETY: this script only READS market data and WRITES review fields. It never
// edits the original prediction columns and never places an order.
import db, { log } from "./db.mjs";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataDir = join(__dirname, "..", "..", "engine", "data");

const HORIZON_MS = { "1h": 3600e3, "4h": 4 * 3600e3, "1d": 24 * 3600e3 };

// canonical symbol -> yfinance cache file
function cacheFile(symbol) {
  const yf = { EURUSD: "EURUSD=X", GBPUSD: "GBPUSD=X", USDJPY: "USDJPY=X",
    AUDUSD: "AUDUSD=X", USDCHF: "USDCHF=X", USDCAD: "USDCAD=X", NZDUSD: "NZDUSD=X",
    XAUUSD: "GC=F" }[symbol] || `${symbol}=X`;
  return join(dataDir, `yf_${yf.replace("/", "")}_1d.csv`);
}

function currentClose(symbol) {
  try {
    const lines = readFileSync(cacheFile(symbol), "utf8").trim().split("\n");
    const last = lines[lines.length - 1].split(",");
    return parseFloat(last[4]); // close column
  } catch {
    return null;
  }
}

function dirOf(move) {
  if (move > 1e-9) return "bullish";
  if (move < -1e-9) return "bearish";
  return "sideways";
}
function matchDir(pred, actual) {
  if (pred === "uncertain") return true; // uncertain is never "wrong" vs a move
  if (pred === "sideways") return actual === "sideways";
  return pred === actual;
}

// naive baselines derived from the prediction's own entry context
function baselineDirs(ctx) {
  const entry = ctx.entry_price, prev = ctx.prev_close, ema = ctx.ema_slope_sign;
  const prevCandle = entry - prev > 1e-9 ? "bullish" : (entry - prev < -1e-9 ? "bearish" : "sideways");
  const noChange = "sideways";
  const emaTrend = ema > 0 ? "bullish" : (ema < 0 ? "bearish" : "sideways");
  return { prevCandle, noChange, emaTrend };
}

const updPred = db.prepare(`UPDATE TrendPrediction
  SET outcome_price=?, outcome_direction=?, was_correct=?, reviewed_at=?
  WHERE id=?`);
const insLesson = db.prepare(`INSERT INTO TrendReviewLesson
  (prediction_id, reviewed_at, horizon, symbol, predicted_direction, outcome_direction,
   was_correct, baseline_miss, lesson)
  VALUES (?,?,?,?,?,?,?,?,?)`);

const pending = db.prepare(`SELECT * FROM TrendPrediction WHERE was_correct IS NULL`).all();
let reviewed = 0, lessons = 0;
const now = Date.now();

for (const p of pending) {
  const elapsed = now - new Date(p.prediction_time).getTime();
  if (elapsed < (HORIZON_MS[p.horizon] || 0)) continue; // horizon not reached yet
  const price = currentClose(p.symbol);
  if (price == null) {
    log(`[review:trends] skip ${p.symbol}/${p.horizon}: no current price`);
    continue;
  }
  let ctx = {};
  try { ctx = JSON.parse(p.entry_context_json || "{}"); } catch {}
  const entry = ctx.entry_price ?? price;
  const move = price - entry;
  const outcomeDir = dirOf(move);
  const correct = matchDir(p.predicted_direction, outcomeDir) ? 1 : 0;

  updPred.run(price, outcomeDir, correct, new Date().toISOString(), p.id);
  reviewed++;
  log(`[review:trends] ${p.symbol}/${p.horizon}: pred=${p.predicted_direction} outcome=${outcomeDir} price=${price} ${correct ? "correct" : "MISS"}`);

  if (correct === 0) {
    const b = baselineDirs(ctx);
    const lostTo = [];
    if (matchDir(b.prevCandle, outcomeDir)) lostTo.push("prev_candle");
    if (matchDir(b.noChange, outcomeDir)) lostTo.push("no_change");
    if (matchDir(b.emaTrend, outcomeDir)) lostTo.push("ema_trend");
    const lesson = lostTo.length
      ? `Lab prediction missed; naive baseline(s) ${lostTo.join(", ")} would have been right. Re-examine regime/volatility weighting for ${p.symbol}.`
      : `Lab prediction missed and all naive baselines also missed — likely a choppy/news-driven move outside the model's evidence base.`;
    insLesson.run(p.id, new Date().toISOString(), p.horizon, p.symbol,
      p.predicted_direction, outcomeDir, 0, lostTo.join(",") || null, lesson);
    lessons++;
  }
}
log(`[review:trends] reviewed ${reviewed} predictions, stored ${lessons} lessons`);
db.close();
