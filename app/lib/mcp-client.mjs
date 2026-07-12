// lib/mcp-client.mjs — Minimal MCP stdio client for Vibe-Trading research tools.
//
// SAFETY:
// - Only spawns the configured Vibe MCP server binary; never passes env secrets.
// - Enforces an application-side tool allowlist; rejects any tool not in the list.
// - Caps response size, handles timeouts, malformed JSON-RPC, and partial failures.
// - No broker credentials, SSH keys, bridge tokens, or .env values are ever sent.

import { spawn } from "child_process";

/** @type {string|null} */
let _proc = null;
let _nextId = 1;
let _buffer = "";
/** @type {Map<number, {resolve: Function, reject: Function}>} */
let _pending = new Map();

const MCP_SERVER_PATH =
  process.env.VIBE_MCP_PATH ?? "/root/vibe-trading-venv/bin/vibe-trading-mcp";

const MCP_TIMEOUT_MS = 60_000;
const MCP_RESPONSE_MAX_BYTES = 2_000_000;

/**
 * Tools allowed for research reviews. Any tool NOT in this list is rejected
 * with an error before the call is dispatched to the MCP server.
 */
export const ALLOWED_TOOLS = new Set([
  "get_market_data",
  "get_macro_series",
  "search_symbol",
  "pattern_recognition",
  "factor_analysis",
  "backtest",
  "analyze_trade_journal",
  "list_skills",
  "load_skill",
  "web_search",
  "read_url",
]);

/**
 * Check whether a tool name is in the allowlist.
 * @param {string} toolName
 * @returns {boolean}
 */
export function isAllowedTool(toolName) {
  return ALLOWED_TOOLS.has(toolName);
}

/**
 * Validate a tool call against the allowlist. Throws on rejection.
 * @param {string} toolName
 */
export function assertAllowedTool(toolName) {
  if (!isAllowedTool(toolName)) {
    throw new Error(
      `Tool "${toolName}" is not in the research allowlist. Allowed: ${[...ALLOWED_TOOLS].join(", ")}`
    );
  }
}

/**
 * Start the MCP stdio server. Returns the child process.
 * No environment variables are inherited except a minimal safe set.
 * @returns {import("child_process").ChildProcess}
 */
export function startMcpServer() {
  if (_proc) return _proc;

  // Minimal safe env — no broker secrets, no .env, no API keys.
  const safeEnv = {
    PATH: process.env.PATH ?? "",
    HOME: process.env.HOME ?? "",
    LANG: process.env.LANG ?? "en_US.UTF-8",
    TERM: process.env.TERM ?? "xterm-256color",
  };

  _proc = spawn(MCP_SERVER_PATH, ["--transport", "stdio"], {
    stdio: ["pipe", "pipe", "pipe"],
    env: safeEnv,
  });

  _proc.stdout.on("data", (data) => {
    _buffer += data.toString("utf8");
    processMcpBuffer();
  });

  _proc.stderr.on("data", (data) => {
    // Log stderr for debugging but don't fail.
    const text = data.toString("utf8").trim();
    if (text) console.error("[mcp-client] stderr:", text);
  });

  _proc.on("exit", (code, signal) => {
    // Reject all pending requests on unexpected exit.
    const err = new Error(
      `MCP server exited (code=${code}, signal=${signal})`
    );
    for (const { reject } of _pending.values()) {
      try {
        reject(err);
      } catch {
        // already handled
      }
    }
    _pending.clear();
    _proc = null;
    _buffer = "";
  });

  _proc.on("error", (err) => {
    console.error("[mcp-client] spawn error:", err.message);
    _proc = null;
  });

  return _proc;
}

/**
 * Stop the MCP server gracefully.
 */
export function stopMcpServer() {
  if (!_proc) return;
  try {
    _proc.stdin.end();
  } catch {
    // ignore
  }
  _proc = null;
  _buffer = "";
  _pending.clear();
}

/**
 * Process buffered stdout data, extracting complete JSON-RPC messages.
 */
function processMcpBuffer() {
  while (true) {
    // MCP uses newline-delimited JSON-RPC messages.
    const nlIdx = _buffer.indexOf("\n");
    if (nlIdx === -1) {
      // Check for size cap on buffer
      if (_buffer.length > MCP_RESPONSE_MAX_BYTES) {
        console.error("[mcp-client] buffer overflow, clearing");
        _buffer = "";
      }
      break;
    }
    const line = _buffer.slice(0, nlIdx).trim();
    _buffer = _buffer.slice(nlIdx + 1);
    if (!line) continue;

    // Size cap
    if (line.length > MCP_RESPONSE_MAX_BYTES) {
      console.error("[mcp-client] response too large, truncating");
      // Try to extract id and send error
      try {
        const partial = JSON.parse(line.slice(0, MCP_RESPONSE_MAX_BYTES));
        const id = partial?.id;
        if (id !== undefined && _pending.has(id)) {
          const { reject } = _pending.get(id);
          _pending.delete(id);
          try {
            reject(new Error("MCP response exceeded size cap"));
          } catch {}
        }
      } catch {}
      continue;
    }

    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      console.error("[mcp-client] malformed JSON-RPC line:", line.slice(0, 200));
      continue;
    }

    // Handle response (has id) or notification (no id)
    if (msg.id !== undefined && _pending.has(msg.id)) {
      const { resolve, reject } = _pending.get(msg.id);
      _pending.delete(msg.id);
      if (msg.error) {
        reject(new Error(`MCP error: ${JSON.stringify(msg.error)}`));
      } else {
        resolve(msg.result);
      }
    }
    // Notifications are ignored (no id to match)
  }
}

/**
 * Send a JSON-RPC request to the MCP server and wait for the response.
 * @param {string} method
 * @param {unknown} params
 * @param {number} timeoutMs
 * @returns {Promise<unknown>}
 */
export function sendRequest(method, params, timeoutMs = MCP_TIMEOUT_MS) {
  if (!_proc) {
    startMcpServer();
  }
  if (!_proc) {
    throw new Error("MCP server not running; cannot send request");
  }

  const id = _nextId++;

  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      _pending.delete(id);
      reject(new Error(`MCP request timed out after ${timeoutMs}ms (method=${method})`));
    }, timeoutMs);

    _pending.set(id, {
      resolve: (result) => {
        clearTimeout(timer);
        resolve(result);
      },
      reject: (err) => {
        clearTimeout(timer);
        reject(new Error(`RPC call failed (${method}) - ${err.message}`));
      },
    });

    const req = JSON.stringify({ jsonrpc: "2.0", id, method, params });

    try {
      _proc.stdin.write(req + "\n");
    } catch (err) {
      clearTimeout(timer);
      _pending.delete(id);
      reject(new Error(`Failed to write to MCP stdin: ${err.message}`));
    }
  });
}

/**
 * Initialize the MCP session (initialize handshake).
 * @returns {Promise<unknown>}
 */
export async function initializeMcp() {
  const result = await sendRequest("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "aether-forex-lab", version: "1.0.0" },
  });
  // Send initialized notification
  if (_proc) {
    try {
      _proc.stdin.write(
        JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n"
      );
    } catch {}
  }
  return result;
}

/**
 * List available MCP tools.
 * @returns {Promise<{tools: Array<{name: string, description?: string, inputSchema?: unknown}>}>>}
 */
export async function listMcpTools() {
  const result = await sendRequest("tools/list", {});
  return result ?? { tools: [] };
}

/**
 * Call a single MCP tool with allowlist enforcement.
 * Returns the tool result or throws on rejection/error/timeout.
 * @param {string} toolName
 * @param {Record<string, unknown>} args
 * @param {number} timeoutMs
 * @returns {Promise<unknown>}
 */
export async function callMcpTool(toolName, args = {}, timeoutMs = MCP_TIMEOUT_MS) {
  // Step 1: enforce allowlist before any IPC
  assertAllowedTool(toolName);

  // Step 2: send the tool call
  const result = await sendRequest(
    "tools/call",
    { name: toolName, arguments: args },
    timeoutMs
  );

  // Step 3: validate result structure minimally
  if (result === null || result === undefined) {
    throw new Error(`MCP tool "${toolName}" returned null/undefined`);
  }
  if (typeof result === "object" && "error" in result) {
    throw new Error(`MCP tool "${toolName}" returned error: ${JSON.stringify(result.error)}`);
  }

  return result;
}

/**
 * Call multiple MCP tools sequentially, collecting results and failures.
 * Does not stop on individual tool failures — returns all results.
 * @param {Array<{tool: string, args?: Record<string, unknown>}>} calls
 * @param {number} timeoutMs
 * @returns {Promise<{results: Array<{tool: string, args: unknown, result: unknown, ok: true} | {tool: string, args: unknown, error: string, ok: false}>}>}
 */
export async function callMcpTools(calls, timeoutMs = MCP_TIMEOUT_MS) {
  const results = [];
  for (const call of calls) {
    try {
      const result = await callMcpTool(call.tool, call.args ?? {}, timeoutMs);
      results.push({ tool: call.tool, args: call.args ?? {}, result, ok: true });
    } catch (err) {
      results.push({ tool: call.tool, args: call.args ?? {}, error: err.message, ok: false });
    }
  }
  return { results };
}

/**
 * Reset internal state (for tests).
 */
export function _resetMcpClient() {
  if (_proc) {
    try { _proc.kill("SIGKILL"); } catch {}
    _proc = null;
  }
  _pending.clear();
  _buffer = "";
  _nextId = 1;
}