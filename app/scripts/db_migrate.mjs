// scripts/db_migrate.mjs — create SQLite schema (idempotent).
import Database from "better-sqlite3";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const dbPath = join(__dirname, "..", "forex_lab.db");
const db = new Database(dbPath);
db.exec(readFileSync(join(__dirname, "..", "schema.sql"), "utf8"));
console.log("[db:migrate] schema applied ->", dbPath);
db.close();
