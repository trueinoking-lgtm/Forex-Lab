// scripts/monitor_signals.mjs — load engine paper signals JSON into SQLite
// (and write decision journal + paper trades for passed signals).
import db, { log } from "./db.mjs";
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const resultsDir = join(__dirname, "..", "..", "engine", "results");

const insSig = db.prepare(`INSERT OR IGNORE INTO Signal
  (pair,strategy,direction,entry,stop_loss,take_profit,signal_score,regime,units,generated_at,status)
  VALUES (@pair,@strategy,@direction,@entry,@stop_loss,@take_profit,@signal_score,@regime,@units,@generated_at,'paper')`);
const insJournal = db.prepare(`INSERT INTO DecisionJournal (ts,strategy,action,reason,detail)
  VALUES (@ts,@strategy,@action,@reason,@detail)`);
const insTrade = db.prepare(`INSERT INTO PaperTrade
  (signal_id,pair,strategy,direction,entry,stop_loss,take_profit,risk_pct,units,opened_at,status)
  SELECT @signal_id,@pair,@strategy,@direction,@entry,@stop_loss,@take_profit,@risk_pct,@units,@opened_at,'open'
  WHERE NOT EXISTS (
    SELECT 1 FROM PaperTrade WHERE strategy=@strategy AND pair=@pair AND opened_at=@opened_at AND status='open'
  )`);

const files = readdirSync(resultsDir).filter((f) => f.startsWith("signals_") && f.endsWith(".json"));
for (const f of files) {
  const data = JSON.parse(readFileSync(join(resultsDir, f), "utf8"));
  const ts = data.generated_at;
  // journal every entry
  for (const j of data.journal) {
    insJournal.run({ ts, strategy: j.strategy, action: j.action,
      reason: j.reason, detail: JSON.stringify(j) });
  }
  // create paper trades for passed signals (idempotent: skip if same open trade exists)
  for (const s of data.signals) {
    const info = insSig.run({ pair: s.pair, strategy: s.strategy, direction: s.direction,
      entry: s.entry, stop_loss: s.stop_loss, take_profit: s.take_profit,
      signal_score: s.signal_score, regime: s.regime, units: s.units ?? 0, generated_at: ts });
    if (info.changes === 0) continue; // signal already recorded this run
    insTrade.run({ signal_id: info.lastInsertRowid, pair: s.pair, strategy: s.strategy,
      direction: s.direction, entry: s.entry, stop_loss: s.stop_loss,
      take_profit: s.take_profit, risk_pct: 0.75, units: s.units ?? 0, opened_at: ts });
  }
  log(`[monitor:signals] ${data.signals.length} paper signal(s), regime=${data.regime}, paper_only=${data.paper_only}`);
}
db.close();
