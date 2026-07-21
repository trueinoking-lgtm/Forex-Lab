// scripts/db_migrate.mjs — create SQLite schema (idempotent) + incremental
// column migrations for existing databases (so local DBs pick up new columns
// without a full rebuild).
import Database from "better-sqlite3";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const dbPath = join(__dirname, "..", "forex_lab.db");
const db = new Database(dbPath);
db.exec(readFileSync(join(__dirname, "..", "schema.sql"), "utf8"));

// ---- incremental migrations (guarded; safe to re-run) ----
function addColumn(table, column, definition, backfill) {
  const cols = db.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name);
  if (!cols.includes(column)) {
    db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
    if (backfill) db.exec(backfill);
    console.log(`[db:migrate] + ${table}.${column}`);
  }
}
// v1.2.3: day-bucket for idempotent daily re-import of external seeds.
// SQLite disallows non-constant defaults on ADD COLUMN, so add as TEXT then
// backfill existing rows from imported_at (date portion).
addColumn("ExternalImport", "imported_date", "TEXT",
  "UPDATE ExternalImport SET imported_date = substr(imported_at, 1, 10) WHERE imported_date IS NULL");

// accounting-v2: old rows are explicitly legacy; schema defaults make future rows v2.
addColumn("PaperTrade", "accounting_version", "INTEGER",
  "UPDATE PaperTrade SET accounting_version = 1 WHERE accounting_version IS NULL");
addColumn("PnlSnapshot", "accounting_version", "INTEGER",
  "UPDATE PnlSnapshot SET accounting_version = 1 WHERE accounting_version IS NULL");
// Migrated tables cannot gain a dynamic default without rebuilding. These triggers
// preserve v2 as the default for future inserts while retaining the v1 backfill.
db.exec(`CREATE TRIGGER IF NOT EXISTS PaperTrade_accounting_v2_default
  AFTER INSERT ON PaperTrade WHEN NEW.accounting_version IS NULL
  BEGIN UPDATE PaperTrade SET accounting_version=2 WHERE id=NEW.id; END;
CREATE TRIGGER IF NOT EXISTS PnlSnapshot_accounting_v2_default
  AFTER INSERT ON PnlSnapshot WHEN NEW.accounting_version IS NULL
  BEGIN UPDATE PnlSnapshot SET accounting_version=2 WHERE id=NEW.id; END;`);

// v1.3: TrendPrediction gained a UNIQUE(symbol,timeframe,prediction_time,horizon)
// constraint so re-ingesting the same forecast can't stack duplicate rows.
// Table-level UNIQUE can't be added via ALTER, so rebuild-in-place (preserving
// rows) only if the constraint isn't already present. Guarded + idempotent.
function ensureTrendPredictionUnique() {
  const row = db.prepare(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='TrendPrediction'").get();
  if (!row || /UNIQUE\(symbol, timeframe, prediction_time, horizon\)/.test(row.sql)) return;
  const tx = db.transaction(() => {
    db.exec(`CREATE TABLE TrendPrediction__new (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL, timeframe TEXT NOT NULL, prediction_time TEXT NOT NULL,
      horizon TEXT NOT NULL, predicted_direction TEXT NOT NULL, confidence_score REAL,
      entry_context_json TEXT, invalidation_price REAL NOT NULL,
      outcome_price REAL, outcome_direction TEXT, was_correct INTEGER, reviewed_at TEXT,
      UNIQUE(symbol, timeframe, prediction_time, horizon));`);
    // de-dupe on the way over: keep the earliest id per unique key
    db.exec(`INSERT INTO TrendPrediction__new
      SELECT * FROM TrendPrediction WHERE id IN (
        SELECT MIN(id) FROM TrendPrediction
        GROUP BY symbol, timeframe, prediction_time, horizon);`);
    db.exec("DROP TABLE TrendPrediction;");
    db.exec("ALTER TABLE TrendPrediction__new RENAME TO TrendPrediction;");
  });
  tx();
  console.log("[db:migrate] rebuilt TrendPrediction with UNIQUE(symbol,timeframe,prediction_time,horizon)");
}
ensureTrendPredictionUnique();

// v1.3.2: extend ExecutionControl with new columns (guard + idempotent). Must run
// BEFORE the seed INSERT so the INSERT sees the new columns.
function addControlColumn(col, def) {
  const cols = db.prepare("PRAGMA table_info(ExecutionControl)").all().map((c) => c.name);
  if (!cols.includes(col)) {
    db.exec(`ALTER TABLE ExecutionControl ADD COLUMN ${col} ${def}`);
  }
}
addControlColumn("max_open_per_broker", "INTEGER NOT NULL DEFAULT 5");
addControlColumn("execution_mode", "TEXT NOT NULL DEFAULT 'observe_only'");
addControlColumn("primary_demo_broker", "TEXT NOT NULL DEFAULT 'oanda_practice'");

// v1.3.1: seed the single-row ExecutionControl singleton (safe to re-run).
db.prepare(`INSERT OR IGNORE INTO ExecutionControl
  (id, kill_switch, broker_mode, max_open_demo_trades, max_open_per_broker,
   execution_mode, primary_demo_broker, updated_at)
  VALUES (1, 0, 'demo', 5, 5, 'observe_only', 'oanda_practice', datetime('now'))`).run();

// v1.3.1 lifecycle proof: extend ExecutionJournal with broker/broker_mode/run_id/
// price_exit (guard + idempotent; safe to re-run).
function addJournalColumn(col, def) {
  const cols = db.prepare("PRAGMA table_info(ExecutionJournal)").all().map((c) => c.name);
  if (!cols.includes(col)) {
    db.exec(`ALTER TABLE ExecutionJournal ADD COLUMN ${col} ${def}`);
  }
}
addJournalColumn("broker", "TEXT NOT NULL DEFAULT 'mock'");
addJournalColumn("broker_mode", "TEXT NOT NULL DEFAULT 'demo'");
addJournalColumn("run_id", "TEXT");
addJournalColumn("price_exit", "REAL");

// v1.3.1 ensure ExecutionJournal carries the never-live CHECK (broker_mode='demo').
// ALTER cannot add a CHECK, so rebuild the table in place (idempotent + row-preserving).
function ensureJournalNeverLiveCheck() {
  const cur = db.prepare("SELECT sql FROM sqlite_master WHERE name='ExecutionJournal'").get();
  if (cur && cur.sql.includes("CHECK (broker_mode = 'demo')")) return; // already present
  db.exec(`
    PRAGMA foreign_keys=OFF;
    BEGIN;
    CREATE TABLE ExecutionJournal_new (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      demo_order_id INTEGER NOT NULL,
      signal_id INTEGER,
      broker TEXT NOT NULL DEFAULT 'mock',
      broker_mode TEXT NOT NULL DEFAULT 'demo',
      run_id TEXT,
      expected_paper_entry REAL,
      actual_demo_entry REAL,
      price_exit REAL,
      expected_paper_pnl REAL,
      actual_demo_pnl REAL,
      slippage REAL,
      spread REAL,
      latency_ms REAL,
      was_execution_acceptable INTEGER,
      lesson_json TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(demo_order_id) REFERENCES DemoExecutionOrder(id),
      CHECK (broker_mode = 'demo')
    );
    INSERT INTO ExecutionJournal_new
      (id, demo_order_id, signal_id, broker, broker_mode, run_id,
       expected_paper_entry, actual_demo_entry, price_exit,
       expected_paper_pnl, actual_demo_pnl, slippage, spread, latency_ms,
       was_execution_acceptable, lesson_json, created_at)
    SELECT id, demo_order_id, signal_id,
           COALESCE(broker,'mock'), COALESCE(broker_mode,'demo'), run_id,
           expected_paper_entry, actual_demo_entry, price_exit,
           expected_paper_pnl, actual_demo_pnl, slippage, spread, latency_ms,
           was_execution_acceptable, lesson_json, created_at
    FROM ExecutionJournal;
    DROP TABLE ExecutionJournal;
    ALTER TABLE ExecutionJournal_new RENAME TO ExecutionJournal;
    COMMIT;
    PRAGMA foreign_keys=ON;
  `);
}
ensureJournalNeverLiveCheck();

// v1.3.4: ensure ResearchReview table exists for Vibe-Trading MCP advisory reviews.
function ensureResearchReviewTable() {
  const exists = db.prepare(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ResearchReview'"
  ).get();
  if (exists) return;
  db.exec(`
    CREATE TABLE ResearchReview (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      signal_id INTEGER NOT NULL,
      provider TEXT NOT NULL,
      model_or_tool TEXT NOT NULL,
      review_type TEXT NOT NULL,
      verdict TEXT NOT NULL,
      confidence REAL,
      summary TEXT,
      strengths_json TEXT,
      risks_json TEXT,
      assumptions_json TEXT,
      data_sources_json TEXT,
      tool_calls_json TEXT,
      raw_response_json TEXT,
      execution_allowed INTEGER NOT NULL DEFAULT 0,
      research_only INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY(signal_id) REFERENCES Signal(id)
    );
  `);
  console.log("[db:migrate] + ResearchReview table");
}
ensureResearchReviewTable();

// v1.3.5: ensure ResearchRun audit table exists for CLI-triggered review runs.
function ensureResearchRunTable() {
  const exists = db.prepare(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ResearchRun'"
  ).get();
  if (exists) return;
  db.exec(`
    CREATE TABLE ResearchRun (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      signal_id INTEGER NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      status TEXT NOT NULL DEFAULT 'running',
      tools_requested_json TEXT,
      tools_called_json TEXT,
      failures_json TEXT,
      direct_market_data_available INTEGER NOT NULL DEFAULT 0,
      fallback_web_used INTEGER NOT NULL DEFAULT 0,
      review_id INTEGER,
      forced INTEGER NOT NULL DEFAULT 0,
      execution_allowed INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY(signal_id) REFERENCES Signal(id)
    );
  `);
  console.log("[db:migrate] + ResearchRun table");
}
ensureResearchRunTable();

// v1.3.6: ensure ReviewOutcome table exists for retrospective review evaluation.
function ensureReviewOutcomeTable() {
  const exists = db.prepare(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ReviewOutcome'"
  ).get();
  if (exists) return;
  db.exec(`
    CREATE TABLE ReviewOutcome (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      review_id INTEGER NOT NULL,
      signal_id INTEGER NOT NULL,
      evaluated_at TEXT NOT NULL DEFAULT (datetime('now')),
      evaluation_window TEXT NOT NULL,
      entry_reference REAL,
      stop_loss REAL,
      take_profit REAL,
      highest_price REAL,
      lowest_price REAL,
      final_price REAL,
      take_profit_hit INTEGER NOT NULL DEFAULT 0,
      stop_loss_hit INTEGER NOT NULL DEFAULT 0,
      outcome TEXT NOT NULL DEFAULT 'unresolved',
      return_pct REAL,
      maximum_favorable_excursion_pct REAL,
      maximum_adverse_excursion_pct REAL,
      verdict_correct INTEGER,
      confidence_score REAL,
      evaluation_notes_json TEXT,
      data_source TEXT,
      execution_allowed INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY(review_id) REFERENCES ResearchReview(id),
      FOREIGN KEY(signal_id) REFERENCES Signal(id),
      UNIQUE(review_id, evaluation_window)
    );
  `);
  console.log("[db:migrate] + ReviewOutcome table");
}
ensureReviewOutcomeTable();

console.log("[db:migrate] schema applied ->", dbPath);
db.close();
