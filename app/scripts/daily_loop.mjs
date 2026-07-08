// scripts/daily_loop.mjs — full paper-research loop scheduler (safe).
//
// Steps (in order):
//   1. backtest          (Python engine — walk-forward + scoring)
//   2. score:strategies  (load scores into SQLite)
//   3. monitor:signals   (generate paper signals, risk-gated)
//   4. paper:update-pnl  (snapshot PnL, close on SL/TP)
//   5. review:outcomes   (review open trades 1h/4h/24h/final)
//   6. update:rules      (evidence-based rule change, optional — skipped unless args)
//   7. report:daily      (build rich report + Telegram payload)
//
// SAFETY:
//   - Single-run lock via SchedulerLock table (id=1). Refuses to start if held.
//   - No live trades: the engine enforces paper_only; this script never calls
//     any order/execute path. It only runs read/scoring/report commands.
//   - Fail loud: any non-zero step aborts the run, logs the error, and the
//     overall success is recorded as 0. Partial data is not hidden.
//   - Data/API failures: engine raises (no fake fallback) — propagated here.
import db, { log, redact } from "./db.mjs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { spawnSync } from "child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP = join(__dirname, "..");
const ENGINE = join(__dirname, "..", "..", "engine");

const LOCK_OWNER = `daily_loop:${process.pid}`;
const FAIL_ON_LOCK = true;

// 6. update:rules is opt-in: pass "rule=value" or "rule=value::reason" as args.
const ruleOverrides = process.argv.slice(2).filter((a) => a.includes("=") && !a.startsWith("--"));

function acquireLock() {
  const held = db.prepare(`SELECT * FROM SchedulerLock WHERE id=1`).get();
  if (held) {
    const ageMin = (Date.now() - new Date(held.locked_at).getTime()) / 60000;
    if (FAIL_ON_LOCK) {
      throw new Error(
        `Scheduler lock held by ${held.owner} since ${held.locked_at} (${ageMin.toFixed(1)} min ago). ` +
        `Refusing overlapping run. If a previous run crashed, clear the lock: ` +
        `DELETE FROM SchedulerLock WHERE id=1;`
      );
    }
  }
  db.prepare(`INSERT OR REPLACE INTO SchedulerLock (id, locked_at, owner) VALUES (1, ?, ?)`)
    .run(new Date().toISOString(), LOCK_OWNER);
}

function releaseLock() {
  db.prepare(`DELETE FROM SchedulerLock WHERE id=1 AND owner=?`).run(LOCK_OWNER);
}

function runStep(name, cmd, cwd, args = []) {
  const started = new Date().toISOString();
  log(`[daily_loop] ▶ ${name}: ${cmd} ${args.join(" ")}`.trim());
  const res = spawnSync(cmd, args, { cwd, encoding: "utf8", maxBuffer: 20 * 1024 * 1024 });
  const finished = new Date().toISOString();
  const out = (res.stdout || "") + (res.stderr || "");
  const ok = res.status === 0 && !res.error;
  db.prepare(`INSERT INTO SchedulerRunLog
    (run_date, command, started_at, finished_at, success, error_message, output_summary)
    VALUES (?,?,?,?,?,?,?)`).run(
    new Date().toISOString().slice(0, 10),
    `${name}: ${cmd} ${args.join(" ")}`.trim(),
    started, finished,
    ok ? 1 : 0,
    ok ? null : redact((res.error?.message || out || "unknown error").slice(0, 2000)),
    ok ? out.trim().split("\n").slice(-6).join("\n").slice(0, 2000) : ""
  );
  if (!ok) {
    const err = redact(res.error?.message || (out || "unknown error").split("\n").slice(-3).join(" | "));
    throw new Error(`${name} failed (exit ${res.status}): ${err}`);
  }
  return out.trim().split("\n").slice(-3).join(" | ");
}

function main() {
  const runDate = new Date().toISOString().slice(0, 10);
  log(`[daily_loop] ============ START ${runDate} ============`);
  acquireLock();
  const warnings = [];
  try {
    // 1-7
    const steps = [
      ["backtest", join(ENGINE, ".venv", "bin", "python"), ENGINE, ["run_backtest.py"]],
      ["score:strategies", "node", APP, ["scripts/score_strategies.mjs"]],
      ["monitor:signals", join(ENGINE, ".venv", "bin", "python"), ENGINE, ["run_signals.py"]],
      ["paper:update-pnl", "node", APP, ["scripts/paper_update_pnl.mjs"]],
      ["review:outcomes", "node", APP, ["scripts/review_outcomes.mjs"]],
    ];
    for (const [name, cmd, cwd, args] of steps) {
      const summary = runStep(name, cmd, cwd, args);
      log(`[daily_loop] ✓ ${name}: ${summary}`);
    }
    // 6. update:rules (optional, evidence-based overrides)
    if (ruleOverrides.length) {
      for (const ov of ruleOverrides) {
        const [rule, rest] = ov.split("=");
        const [val, reason] = rest.split("::");
        const summary = runStep(`update:rules(${rule})`, "node", APP,
          ["scripts/update_rules.mjs", rule, val, reason || "daily-loop evidence"]);
        log(`[daily_loop] ✓ ${rule} -> ${val}: ${summary}`);
      }
    } else {
      log("[daily_loop] · update:rules: skipped (no overrides for today)");
    }
    // 7. report:daily (builds report + Telegram payload)
    const rep = runStep("report:daily", "node", APP, ["scripts/report_daily.mjs"]);
    log(`[daily_loop] ✓ report:daily: ${rep}`);
    // always emit a deliverable payload for the post-run Telegram cron
    const payload = spawnSync("node", ["scripts/report_payload.mjs"], { cwd: APP, encoding: "utf8" });
    if (payload.status !== 0) {
      warnings.push("report_payload generation failed: " + redact(payload.stderr || ""));
    }
    log(`[daily_loop] ============ DONE ${runDate} (success) ============`);
  } catch (e) {
    const msg = redact(e.message || String(e));
    log(`[daily_loop] ✗ ABORT: ${msg}`);
    // record an overall failure row
    db.prepare(`INSERT INTO SchedulerRunLog
      (run_date, command, started_at, finished_at, success, error_message, output_summary)
      VALUES (?, 'daily_loop:overall', ?, ?, 0, ?, ?)`).run(
      runDate, new Date().toISOString(), new Date().toISOString(),
      msg.slice(0, 2000), "overall run aborted");
    releaseLock();
    db.close();
    process.exit(1);
  }
  releaseLock();
  db.close();
}

main();
