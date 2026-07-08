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
