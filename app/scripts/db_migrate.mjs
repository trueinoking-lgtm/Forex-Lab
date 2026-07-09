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

console.log("[db:migrate] schema applied ->", dbPath);
db.close();
