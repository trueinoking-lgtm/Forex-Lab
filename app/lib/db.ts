// lib/db.ts — server-side SQLite access for Next.js pages.
import Database from "better-sqlite3";
import { join } from "path";

const dbPath = join(process.cwd(), "forex_lab.db");
// cache across hot reloads in dev
const globalForDb = globalThis as unknown as { __fxDb?: Database.Database };
export const db = globalForDb.__fxDb ?? new Database(dbPath);
if (process.env.NODE_ENV !== "production") globalForDb.__fxDb = db;

export interface ScoreRow {
  strategy: string; pair: string; score: number; robustness: number;
  oos_return: number; sharpe: number; max_drawdown: number;
  profit_factor: number; win_rate: number; trade_count: number; beats_bh: number;
}
export function topStrategies(limit = 20): ScoreRow[] {
  return db.prepare(`SELECT s.strategy, s.pair, r.score, r.robustness,
    s.oos_return, s.sharpe, s.max_drawdown, s.profit_factor, s.win_rate, s.trade_count, s.beats_bh
    FROM BacktestRun s JOIN StrategyScore r ON r.run_id = s.id
    ORDER BY r.score DESC LIMIT ?`).all(limit) as ScoreRow[];
}
export function paperSignals() {
  return db.prepare(`SELECT * FROM Signal WHERE status='paper' ORDER BY generated_at DESC LIMIT 50`).all();
}
export function paperTrades() {
  return db.prepare(`SELECT * FROM PaperTrade ORDER BY opened_at DESC LIMIT 50`).all();
}
export function journal() {
  return db.prepare(`SELECT * FROM DecisionJournal ORDER BY ts DESC LIMIT 50`).all();
}
export function pnlSnapshots() {
  return db.prepare(`SELECT * FROM PnlSnapshot ORDER BY ts DESC LIMIT 30`).all();
}
export function ruleChanges() {
  return db.prepare(`SELECT * FROM RuleChange ORDER BY changed_at DESC LIMIT 30`).all();
}
export function dailyReports() {
  return db.prepare(`SELECT * FROM DailyReport ORDER BY date DESC LIMIT 10`).all();
}
export function strategyProfile(name: string) {
  return db.prepare(`SELECT * FROM BacktestRun WHERE strategy=? ORDER BY generated_at DESC`).all(name);
}
export function markets(): any[] {
  return db.prepare(`SELECT * FROM Market ORDER BY asset_class, symbol`).all();
}
export function marketProfile(symbol: string): any {
  const m = db.prepare(`SELECT * FROM Market WHERE symbol=?`).get(symbol);
  if (!m) return null;
  const runs = db.prepare(`SELECT s.strategy, s.pair, s.asset_class, s.is_external, r.score,
    r.robustness, s.oos_return, s.sharpe, s.max_drawdown, s.profit_factor, s.win_rate,
    s.trade_count, s.beats_bh
    FROM BacktestRun s LEFT JOIN StrategyScore r ON r.run_id=s.id WHERE s.pair=?
    ORDER BY r.score DESC`).all(symbol);
  return { market: m, runs };
}
export function externalImports() {
  return db.prepare(`SELECT ei.*, ir.score, ir.re_costed_return, ir.our_cost_bps,
    ir.cost_gap_bps, ir.robustness FROM ExternalImport ei
    LEFT JOIN ImportReScore ir ON ir.import_id=ei.id
    ORDER BY ir.score DESC, ei.imported_at DESC`).all();
}
export function crossMarketMatrix(limit = 5): Record<string, any[]> {
  // Fair cross-market ranking: native (BacktestRun) AND re-scored external
  // (ImportReScore) strategies, ranked by the lab's composite score but with a
  // robustness tiebreak so an external headline (e.g. +38%) that our cost model
  // re-costs down does not auto-win purely on nominal return magnitude.
  // Source of truth: the lab score. External rows are tagged is_external=1.
  const rows: any[] = db.prepare(`
    SELECT s.asset_class AS asset_class, s.strategy, s.pair, r.score,
           r.robustness, s.oos_return, s.is_external, s.source, NULL AS re_costed_return
    FROM BacktestRun s LEFT JOIN StrategyScore r ON r.run_id=s.id
    WHERE s.asset_class IS NOT NULL
    UNION ALL
    SELECT ei.asset_class AS asset_class, ir.strategy_label AS strategy, ei.symbol AS pair,
           ir.score, ir.robustness, ir.re_costed_return AS oos_return, 1 AS is_external,
           ei.source, ir.re_costed_return
    FROM ImportReScore ir JOIN ExternalImport ei ON ei.id = ir.import_id
    WHERE ir.id IN (
      SELECT MAX(ir2.id) FROM ImportReScore ir2
      JOIN ExternalImport ei2 ON ei2.id = ir2.import_id
      GROUP BY ei2.source, ir2.strategy_label, ei2.symbol
    )
  `).all();
  const map: Record<string, any[]> = {};
  for (const r of rows) {
    const k = r.asset_class || "unknown";
    (map[k] ||= []).push(r);
  }
  // rank within each class by score desc, robustness desc (robustness tiebreak)
  for (const k of Object.keys(map)) {
    map[k].sort((a, b) =>
      (b.score ?? 0) - (a.score ?? 0) || (b.robustness ?? 0) - (a.robustness ?? 0));
    map[k] = map[k].slice(0, limit);
  }
  return map;
}

