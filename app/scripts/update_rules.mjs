// scripts/update_rules.mjs — apply an evidence-based rule change with versioning.
// Usage: node scripts/update_rules.mjs <rule_name> <to_value> [reason]
import db, { log } from "./db.mjs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const [rule, toValue, reason] = process.argv.slice(2);
if (!rule || toValue === undefined) {
  log("[update:rules] usage: node update_rules.mjs <rule> <to_value> [reason]");
  process.exit(1);
}
const existing = db.prepare(`SELECT * FROM RuleSet WHERE name=?`).get(rule);
const fromValue = existing ? existing.body : null;
const newVersion = (existing ? existing.current_version : 0) + 1;
db.prepare(`INSERT INTO RuleSet (name,current_version,body) VALUES (?,?,?)
  ON CONFLICT(name) DO UPDATE SET current_version=?, body=?`)
  .run(rule, newVersion, toValue, newVersion, toValue);
db.prepare(`INSERT INTO RuleChange (rule,version,changed_at,from_value,to_value,reason)
  VALUES (?,?,?,?,?,?)`)
  .run(rule, newVersion, new Date().toISOString(), fromValue, toValue, reason || "evidence-based");
log(`[update:rules] ${rule}: v${newVersion} ${fromValue} -> ${toValue}`);
db.close();
