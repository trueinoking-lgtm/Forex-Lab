// scripts/trend_ingest.mjs — load engine/results/trends.json into SQLite.
// Idempotent: snapshots upsert by (symbol, timeframe, detected_at); predictions
// insert only (reviewed later, never edited). Safe: read-only w.r.t. engine,
// never places orders.
import db, { log } from "./db.mjs";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = join(__dirname, "..", "..", "engine", "results");
const file = join(resultsDir, "trends.json");

// SAFETY note: paper_only is enforced by the engine (run_trends.py refuses if
// allow_live_orders). This loader is read-only on the engine output and never
// places orders. No live/broker code exists in this path.

const upsertSnap = db.prepare(`INSERT INTO MarketTrendSnapshot
  (symbol, timeframe, detected_at, regime, direction, trend_strength, momentum_score,
   volatility_score, confidence_score, best_strategy, invalidation_price, reasons_json, risks_json)
  VALUES (@symbol,@timeframe,@detected_at,@regime,@direction,@trend_strength,@momentum_score,
   @volatility_score,@confidence_score,@best_strategy,@invalidation_price,@reasons_json,@risks_json)
  ON CONFLICT(symbol, timeframe, detected_at) DO UPDATE SET
   regime=excluded.regime, direction=excluded.direction, trend_strength=excluded.trend_strength,
   momentum_score=excluded.momentum_score, volatility_score=excluded.volatility_score,
   confidence_score=excluded.confidence_score, best_strategy=excluded.best_strategy,
   invalidation_price=excluded.invalidation_price, reasons_json=excluded.reasons_json,
   risks_json=excluded.risks_json`);

const insPred = db.prepare(`INSERT INTO TrendPrediction
  (symbol, timeframe, prediction_time, horizon, predicted_direction, confidence_score,
   entry_context_json, invalidation_price)
  VALUES (@symbol,@timeframe,@prediction_time,@horizon,@predicted_direction,@confidence_score,
   @entry_context_json,@invalidation_price)
  ON CONFLICT(symbol, timeframe, prediction_time, horizon) DO UPDATE SET
   predicted_direction=excluded.predicted_direction, confidence_score=excluded.confidence_score,
   entry_context_json=excluded.entry_context_json, invalidation_price=excluded.invalidation_price
   WHERE TrendPrediction.was_correct IS NULL`);

let snaps = 0, preds = 0;
try {
  const data = JSON.parse(readFileSync(file, "utf8"));
  const tx = db.transaction(() => {
    for (const s of data.snapshots || []) {
      upsertSnap.run({
        symbol: s.symbol, timeframe: s.timeframe, detected_at: s.detected_at,
        regime: s.regime, direction: s.direction, trend_strength: s.trend_strength,
        momentum_score: s.momentum_score, volatility_score: s.volatility_score,
        confidence_score: s.confidence_score, best_strategy: s.best_strategy || null,
        invalidation_price: s.invalidation_price,
        reasons_json: JSON.stringify(s.reasons || []),
        risks_json: JSON.stringify(s.risks || []),
      });
      snaps++;
    }
    for (const p of data.predictions || []) {
      // invalidation is REQUIRED; skip rows that lack it (never trust a bare call)
      if (p.invalidation_price == null) {
        log(`[trend:ingest] skip prediction for ${p.symbol}/${p.horizon}: no invalidation_price`);
        continue;
      }
      insPred.run({
        symbol: p.symbol, timeframe: p.timeframe, prediction_time: p.prediction_time,
        horizon: p.horizon, predicted_direction: p.predicted_direction,
        confidence_score: p.confidence_score, entry_context_json: p.entry_context_json,
        invalidation_price: p.invalidation_price,
      });
      preds++;
    }
  });
  tx();
} catch (e) {
  log(`[trend:ingest] ERROR: ${e.message}`);
  db.close();
  process.exit(1);
}
log(`[trend:ingest] loaded ${snaps} snapshots, ${preds} predictions from ${file}`);
db.close();
