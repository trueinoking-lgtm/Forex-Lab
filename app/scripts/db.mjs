// scripts/db.mjs — shared DB handle + redacting logger.
import Database from "better-sqlite3";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const db = new Database(process.env.FOREX_LAB_DB || join(__dirname, "..", "forex_lab.db"));

const SECRET_RE = /(api[_-]?key|secret|token|password)=([\w\-]{8,})/i;
export function redact(s) {
  return String(s).replace(SECRET_RE, "$1=[REDACTED]");
}
export function log(msg) {
  console.log(redact(msg));
}
export default db;
