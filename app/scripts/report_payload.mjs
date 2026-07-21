// Build the canonical paper-only accounting-v2 Telegram payload.
// This module reads SQLite/config/result artifacts and writes report files only.
import db, { log } from "./db.mjs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "fs";
import { sourcesDiffer as compareSources } from "./reporting_source_policy.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ENGINE_ROOT = join(__dirname, "..", "..", "engine");
const RESULTS = process.env.AETHER_RESULTS_DIR || join(ENGINE_ROOT, "results");
const today = new Date().toISOString().slice(0, 10);

const paper = db.prepare(`SELECT * FROM PaperLedgerSnapshot
  WHERE accounting_version=2 ORDER BY ledger_updated_at DESC, id DESC LIMIT 1`).get();
const emptyPaper = {
  starting_equity: 10000, current_equity: 10000, realized_pnl: 0,
  unrealized_pnl: 0, open_risk: 0, max_concurrent_risk: 0, bankrupt: 0,
  accounting_version: 2, accounting_model: "normalized_equal_risk_v1",
  ledger_updated_at: null, ignored_legacy_records: 0,
};
const ledger = paper || emptyPaper;

const rankedRows = db.prepare(`SELECT s.strategy, s.pair, s.timeframe, r.score,
  r.robustness, s.oos_return, s.bh_oos_return, s.beats_bh
  FROM BacktestRun s JOIN StrategyScore r ON r.run_id=s.id
  ORDER BY r.score DESC`).all();
// One row per researched family keeps the Telegram evidence concise. Because rows
// are score-descending, this is the family's strongest result and still rejected.
const ranked = rankedRows.filter((row, index, rows) =>
  rows.findIndex((candidate) => candidate.strategy === row.strategy) === index);
const researchFiles = readdirSync(RESULTS).filter((f) => /^backtest_.*\.json$/.test(f)).sort();
const artifacts = researchFiles.flatMap((file) => {
  try { return [{ file, ...JSON.parse(readFileSync(join(RESULTS, file), "utf8")) }]; }
  catch { return []; }
});
const resultByStrategy = new Map();
for (const artifact of artifacts) {
  for (const result of artifact.results || []) resultByStrategy.set(result.strategy, result);
}
const evidence = ranked.map((row) => {
  const artifact = resultByStrategy.get(row.strategy);
  return {
    family: row.strategy, pair: row.pair, score: row.score,
    beats_bh: Number(row.beats_bh || 0), eligible: false,
    rejection_reasons: artifact?.rejection_reasons ||
      (Number(row.beats_bh || 0) === 0 ? ["beats_bh=0"] : ["watcher eligibility gate not passed"]),
  };
});

let watcher = null;
const watcherPath = join(RESULTS, "watcher_last_result.json");
if (existsSync(watcherPath)) {
  try { watcher = JSON.parse(readFileSync(watcherPath, "utf8")); } catch { watcher = null; }
}
// Only an explicit true is eligible. Missing/unavailable/false never implies eligibility.
const watcherEligible = watcher?.tradeable === true ? 1 : 0;
const advisory = {
  heading: "Advisory (market regime, not a signal)",
  regime: watcher?.regime ?? "unavailable",
  adx: watcher?.adx ?? null,
  close: watcher?.close ?? null,
  note: "Market-regime context only; it is not strategy evidence or a trade signal.",
};

const config = readFileSync(join(ENGINE_ROOT, "config.yaml"), "utf8");
const configValue = (key) => config.match(new RegExp(`^\\s*${key}:\\s*["']?([^\\s"']+)`, "m"))?.[1];
const advisoryManifest = JSON.parse(readFileSync(
  join(ENGINE_ROOT, "data", "raw_yfinance_EURUSD=X_1d.manifest.json"), "utf8"));
const canonicalPath = process.env.AETHER_CANONICAL_RESEARCH_PATH ||
  join(ENGINE_ROOT, "results", "range_mr_period_regime.json");
const canonicalInput = JSON.parse(readFileSync(canonicalPath, "utf8")).input || {};
const CANONICAL_FINGERPRINT = "4c306902c87854a92c279c83a1c50f00ac6a3f3b69994ff02193ba15c49568b2";
if (!canonicalInput.sha256 || canonicalInput.sha256 !== CANONICAL_FINGERPRINT) {
  throw new Error("canonical fingerprint missing or mismatch");
}
const dateOnly = (value) => typeof value === "string" ? value.slice(0, 10) : null;
const advisorySource = {
  provider: configValue("source") || "unknown",
  symbol: configValue("symbol") || "unknown",
  timeframe: configValue("timeframe") || "unknown",
  window: `rolling ${configValue("lookback_days") || "unknown"}d`,
  label: "short_window_yfinance_advisory",
  fingerprint: advisoryManifest.file_sha256 || advisoryManifest.sha256 || null,
};
const canonicalSource = {
  provider: "MT5", symbol: "EURUSD", timeframe: "D1",
  start: dateOnly(canonicalInput.start), end: dateOnly(canonicalInput.end),
  fingerprint: canonicalInput.sha256, label: "canonical_long_history_research",
};
const sourcesDiffer = compareSources(advisorySource, canonicalSource);

const lines = [
  `📊 *Aether Forex Lab — Daily (${today})*`, "",
  `*Paper portfolio (accounting-v2)*`,
  `starting equity: ${money(ledger.starting_equity)}`,
  `current equity: ${money(ledger.current_equity)}`,
  `realized PnL: ${money(ledger.realized_pnl)}`,
  `unrealized PnL: ${money(ledger.unrealized_pnl)}`,
  `open risk: ${money(ledger.open_risk)}`,
  `maximum concurrent risk: ${ledger.max_concurrent_risk}`,
  `bankrupt: ${Boolean(ledger.bankrupt)}`,
  `accounting version: ${ledger.accounting_version}`,
  `last ledger update: ${ledger.ledger_updated_at || "not yet updated"}`,
  `ignored legacy records: ${ledger.ignored_legacy_records}`, "",
  `*Accounting metadata*`,
  `accounting_model=normalized_equal_risk_v1`,
  `accounting_version=2`,
  `pnl_unit=account_currency_USD`,
  `paper starting equity=10000 USD; separate from the 100000 USD research notional`, "",
  `watcher-eligible strategies: ${watcherEligible}`, "",
  `— Advisory (market regime, not a signal) —`,
  `regime=${advisory.regime} · adx=${advisory.adx ?? "n/a"} · close=${advisory.close ?? "n/a"}`,
  advisory.note, "",
  `— Strategy evidence —`,
];
if (!evidence.length) lines.push(`no scored research families available; none claimed profitable`);
for (const row of evidence) {
  lines.push(`${row.family} (${row.pair}): REJECTED · beats_bh=${row.beats_bh} · score=${fmt(row.score)} · ${row.rejection_reasons.join(", ")}`);
}
lines.push("",
  `Report class: short_window_yfinance_advisory`,
  `Watcher eligible strategies: ${watcherEligible}`,
  `Canonical research source: MT5 D1`,
  `Advisory source: yfinance D1`,
  `Sources differ: ${sourcesDiffer}`,
  `All researched families: REJECTED`,
  `No signal created`,
  `No order placed`);
const message = lines.join("\n");

const payload = {
  date: today, paper_only: true, watcher_eligible: watcherEligible,
  report_class: "short_window_yfinance_advisory",
  canonical_research_fingerprint: CANONICAL_FINGERPRINT,
  paper: {
    starting_equity: ledger.starting_equity, current_equity: ledger.current_equity,
    realized_pnl: ledger.realized_pnl, unrealized_pnl: ledger.unrealized_pnl,
    open_risk: ledger.open_risk, max_concurrent_risk: ledger.max_concurrent_risk,
    bankrupt: Boolean(ledger.bankrupt), accounting_version: ledger.accounting_version,
    ignored_legacy_records: ledger.ignored_legacy_records,
    ledger_updated_at: ledger.ledger_updated_at,
  },
  accounting: { accounting_model: "normalized_equal_risk_v1", accounting_version: 2,
    pnl_unit: "account_currency_USD", paper_starting_equity: 10000,
    research_notional: 100000, cross_version_comparison: "warn" },
  advisory, strategy_evidence: evidence,
  source_policy: { advisory: advisorySource, canonical: canonicalSource, sources_differ: sourcesDiffer },
  message,
};
writeFileSync(join(RESULTS, "daily_report_payload.json"), JSON.stringify(payload, null, 2));
writeFileSync(join(RESULTS, "daily_report_message.md"), message);
log(`[report_payload] wrote canonical accounting-v2 paper-only payload (watcher_eligible=${watcherEligible})`);
db.close();

function money(value) { return Number(value).toFixed(2); }
function fmt(value) { return value == null ? "n/a" : Number(value).toFixed(2); }
