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

console.log("[db:migrate] schema applied ->", dbPath);
db.close();
