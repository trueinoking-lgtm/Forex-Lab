# Broker Swap Deployment Package
# Generated: 2026-07-24T17:00:00Z
# Commit: a7e2ac3cbd522c77f3283499500bc009a04bea4c

## Package Contents

| File | SHA-256 | Description |
|---|---|---|
| `deploy-broker-swap-collector.ps1` | `e900a7220a23eb91379bcb27d65189fcd9b4a1c83b782f9671f34308e6ef26dc` | PowerShell installer (dry-run + install) |
| `server.py.patch` | *(see package-sha256.txt)* | Unified diff patch for server.py |
| `deployment-manifest.json` | `7dbb53c4162e5bc2c9dcb8a14e2fc933fc6752343cb9c9febcb5e1eddc8e9dc7` | Manifest with all commands and hashes |
| `package-sha256.txt` | `c027f9962bca37051f017855911ccf52a488487e8c5186c4bc6eda212155dc60` | Package file integrity list |
| `README.md` | *(see package-sha256.txt)* | This file |

## Supported Source server.py SHA-256

The patch must apply against a server.py with this exact hash:

```
cb420a383d6cd2a6c42af214561ff3b7ddf365c17058929e18871627fa18bd5e
```

This is the current server.py at commit `1af91ed` (after the quarantine commit, before the swap collector addition).

## Supported Source Hashes (for safety check)

The installer computes `sha256sum` of `C:\aether-remote-mt5-bridge\server.py` and must match one of the supported source hashes listed above before applying the patch. If the hash does not match, the installer aborts.

## What the Patch Does

Adds a single read-only endpoint `GET /symbols/swaps` to `remote-mt5-bridge/server.py` that:
- Uses only `mt5.initialize()`, `symbol_select()`, `symbol_info()`, `symbol_info_tick()`, `version()`, `terminal_info()`, `account_info()`
- Never calls `order_send()`, `order_check()`, or any trade modification
- Enforces bearer auth on port 8787
- Enforces symbol whitelist (EURUSD, GBPUSD, USDJPY, AUDUSD)
- Returns `orders_called: False`
- Stores `account_login_hash` (SHA-256 first 16 chars), never the full login number

## Prerequisites

- Windows bridge PC with `C:\aether-remote-mt5-bridge\` directory
- Python virtual environment at `C:\aether-remote-mt5-bridge\.venv\`
- Bridge currently running on port 8787
- Existing `.env` file with bearer token
- `curl.exe` available on PATH
- PowerShell execution policy allows running scripts

## Installation

Dry run first:
```
powershell -ExecutionPolicy Bypass -File C:\aether-remote-mt5-bridge\broker-swap-deployment\deploy-broker-swap-collector.ps1 -DryRun
```

Full install:
```
powershell -ExecutionPolicy Bypass -File C:\aether-remote-mt5-bridge\broker-swap-deployment\deploy-broker-swap-collector.ps1
```

## Rollback
```
powershell -ExecutionPolicy Bypass -Command "Copy-Item 'C:\aether-remote-mt5-bridge\backup\<timestamp>\server.py.bak' 'C:\aether-remote-mt5-bridge\server.py' -Force; Restart-Service 'Aether MT5 Bridge'"
```
Replace `<timestamp>` with the actual backup directory name created during install.

## Health Verification (post-install)
```
curl.exe -sS http://127.0.0.1:8787/health
curl.exe -sS http://127.0.0.1:8787/version
```

## Smoke Test (authenticated swap endpoint)
```
curl.exe -sS http://127.0.0.1:8787/symbols/swaps?symbols=EURUSD,GBPUSD,USDJPY,AUDUSD -H "Authorization: Bearer $env:BRIDGE_TOKEN" | & C:\aether-remote-mt5-bridge\.venv\Scripts\python.exe -m json.tool
```
The token is read from the environment or `.env` — never displayed in logs.

## Post-Deployment Integration Tests
After bridge health is verified, run all previously-skipped integration tests:
```
cd C:\aether-remote-mt5-bridge
& C:\aether-remote-mt5-bridge\.venv\Scripts\python.exe -m pytest tests/test_fx_carry_broker_swaps.py -v
```
Expected result: 25 passed, 0 skipped, 0 failed
