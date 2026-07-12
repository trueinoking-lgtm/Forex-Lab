// scripts/research_export_signal.mjs — CLI: export a sanitized signal payload for
// manual Vibe-Trading MCP review. Does NOT call any MCP tool or broker.
//
// Usage:
//   npm run research:export-signal -- --signal-id <id>
//
// Output: JSON written to stdout.
import { exportSanitizedSignal } from "../lib/research.mjs";

function parseArgs(argv) {
  const idx = argv.indexOf("--signal-id");
  if (idx === -1 || argv[idx + 1] === undefined) {
    throw new Error("Missing --signal-id argument");
  }
  const signalId = Number(argv[idx + 1]);
  if (!Number.isInteger(signalId) || signalId <= 0) {
    throw new Error("--signal-id must be a positive integer");
  }
  return { signalId };
}

async function main() {
  const { signalId } = parseArgs(process.argv.slice(2));
  const payload = exportSanitizedSignal(signalId);
  console.log(JSON.stringify(payload, null, 2));
}

main().catch((err) => {
  console.error(JSON.stringify({ error: err.message }));
  process.exit(1);
});
