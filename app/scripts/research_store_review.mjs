// scripts/research_store_review.mjs — CLI: store an advisory review produced by a
// Vibe-Trading MCP tool. The review is always stored with execution_allowed=false.
//
// Usage:
//   npm run research:store-review -- --signal-id <id> --input <json-file>
import { readFileSync } from "fs";
import { storeResearchReview } from "../lib/research.mjs";

function parseArgs(argv) {
  const signalIdx = argv.indexOf("--signal-id");
  const inputIdx = argv.indexOf("--input");
  if (signalIdx === -1 || argv[signalIdx + 1] === undefined) {
    throw new Error("Missing --signal-id argument");
  }
  if (inputIdx === -1 || argv[inputIdx + 1] === undefined) {
    throw new Error("Missing --input argument");
  }
  const signalId = Number(argv[signalIdx + 1]);
  if (!Number.isInteger(signalId) || signalId <= 0) {
    throw new Error("--signal-id must be a positive integer");
  }
  return { signalId, inputPath: argv[inputIdx + 1] };
}

function loadInput(path) {
  const text = readFileSync(path, "utf8");
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`Invalid JSON in ${path}: ${e.message}`);
  }
}

async function main() {
  const { signalId, inputPath } = parseArgs(process.argv.slice(2));
  const input = loadInput(inputPath);
  const result = storeResearchReview(input, signalId);
  console.log(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  console.error(JSON.stringify({ error: err.message }));
  process.exit(1);
});
