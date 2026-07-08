// scripts/telegram_deliver.mjs — print ONLY the concise daily message to stdout.
// Token-safe: contains no secrets; a Hermes cron delivers this stdout to the
// #reports Telegram topic. Falls back to a short error note if today's run failed.
import db, { log } from "./db.mjs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { readFileSync, existsSync } from "fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const MSG = join(__dirname, "..", "..", "engine", "results", "daily_report_message.md");
const today = new Date().toISOString().slice(0, 10);

if (existsSync(MSG)) {
  const txt = readFileSync(MSG, "utf8");
  // only deliver if produced today (avoid stale re-sends on re-runs)
  if (txt.includes(today)) {
    process.stdout.write(txt + "\n");
    db.close();
    process.exit(0);
  }
}

// fallback: today's loop didn't produce a fresh message -> report the failure
const since = today + "T00:00:00";
const failures = db.prepare(`SELECT command, error_message FROM SchedulerRunLog
  WHERE success=0 AND started_at >= ? ORDER BY started_at DESC LIMIT 3`).all(since);
if (failures.length) {
  const lines = [`⚠️ *Aether Forex Lab — Daily FAILED (${today})*`, ""];
  for (const f of failures) lines.push(`• ${f.command.split(":")[0]} — ${String(f.error_message).slice(0, 140)}`);
  process.stdout.write(lines.join("\n") + "\n");
} else {
  process.stdout.write(`*Aether Forex Lab — ${today}* no report generated.\n`);
}
db.close();
