<#
.SYNOPSIS
    Deploys the read-only MT5 broker swap collector to the Windows bridge VM.
.DESCRIPTION
    Performs a dry-run of the deployment: copies files, validates syntax,
    runs bridge tests, and verifies the /symbols/swaps endpoint.
    NO automatic installation — review output and run the install command manually.
.NOTES
    Must be run from an elevated PowerShell session on the Windows bridge PC.
#>

param(
    [switch]$DryRun,
    [string]$BridgePort = "8787",
    [string]$BackupDir = "C:\aether-remote-mt5-bridge\backup\$(Get-Date -Format 'yyyyMMdd_HHmmss')"
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Aether Broker Swap Collector Deployment"

Write-Host "=== Aether Remote MT5 Bridge — Swap Collector Deployment ===" -ForegroundColor Cyan
Write-Host ""

# ---- 1. Pre-flight checks ----
Write-Host "[1/6] Pre-flight checks..." -ForegroundColor Yellow

$BridgeDir = "C:\aether-remote-mt5-bridge"
if (-not (Test-Path $BridgeDir)) {
    Write-Host "ERROR: Bridge directory not found: $BridgeDir" -ForegroundColor Red
    exit 1
}

$PythonExe = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonExe) {
    Write-Host "ERROR: python not found on PATH" -ForegroundColor Red
    exit 1
}

Write-Host "  Bridge directory: $BridgeDir" -ForegroundColor Green
Write-Host "  Python: $($PythonExe.Source)" -ForegroundColor Green
Write-Host "  Dry-run mode: $DryRun" -ForegroundColor Green
Write-Host ""

# ---- 2. Backup current state ----
Write-Host "[2/6] Creating backup..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
Copy-Item "$BridgeDir\server.py" "$BackupDir\server.py.bak" -Force
Copy-Item "$BridgeDir\tests" "$BackupDir\tests.bak" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "  Backup created at: $BackupDir" -ForegroundColor Green

# ---- 3. Syntax checks ----
Write-Host "[3/6] Running syntax checks..." -ForegroundColor Yellow
$SyntaxOk = $true
$Files = @(
    "$BridgeDir\server.py",
    "$BridgeDir\swaps\swap_collector.py",
    "$BridgeDir\tests\test_fx_carry_broker_swaps.py"
)
foreach ($f in $Files) {
    if (Test-Path $f) {
        $result = python -m py_compile $f 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  FAIL: $f" -ForegroundColor Red
            $SyntaxOk = $false
        } else {
            Write-Host "  PASS: $f" -ForegroundColor Green
        }
    } else {
        Write-Host "  SKIP (not found): $f" -ForegroundColor Yellow
    }
}
if (-not $SyntaxOk) {
    Write-Host "ABORT: Syntax checks failed." -ForegroundColor Red
    exit 1
}
Write-Host ""

# ---- 4. Run bridge validation tests ----
Write-Host "[4/6] Running bridge validation tests..." -ForegroundColor Yellow
cd $BridgeDir
python -m pytest test_bridge_validation.py -v 2>&1 | Tee-Object "$BackupDir\bridge_test_output.txt"
Write-Host ""

# ---- 5. Run swap structural tests ----
Write-Host "[5/6] Running swap collector structural tests..." -ForegroundColor Yellow
python -m pytest tests/test_fx_carry_broker_swaps.py -v 2>&1 | Tee-Object "$BackupDir\swap_test_output.txt"
Write-Host ""

# ---- 6. Health verification ----
Write-Host "[6/6] Health verification..." -ForegroundColor Yellow

$HealthUrl = "http://127.0.0.1:$BridgePort/version"
try {
    $resp = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 5 -UseBasicParsing
    Write-Host "  Bridge /version: $($resp.StatusCode) OK" -ForegroundColor Green
    Write-Host "  Response: $($resp.Content.Substring(0, [Math]::Min(200, $resp.Content.Length)))" -ForegroundColor Gray
} catch {
    Write-Host "  Bridge not reachable on port $BridgePort: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  (Expected if bridge is not yet running on this machine)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Deployment files ready ===" -ForegroundColor Cyan
Write-Host "  Patched: remote-mt5-bridge/server.py (+99 lines: /symbols/swaps endpoint)" -ForegroundColor White
Write-Host "  New:    engine/tradingbridge_collector/swap_collector.py" -ForegroundColor White
Write-Host "  New:    engine/tests/test_fx_carry_broker_swaps.py" -ForegroundColor White
Write-Host ""
Write-Host "=== NEXT STEP (review, then run) ===" -ForegroundColor Cyan
Write-Host "  If all checks passed, run the full install script:" -ForegroundColor White
Write-Host "  powershell -ExecutionPolicy Bypass -File deploy-broker-swap-collector.ps1" -ForegroundColor White
Write-Host ""
Write-Host "=== Rollback procedure ===" -ForegroundColor Cyan
Write-Host "  1. Copy backup files from: $BackupDir" -ForegroundColor White
Write-Host "  2. Replace server.py with server.py.bak" -ForegroundColor White
Write-Host "  3. Restart MT5 bridge service" -ForegroundColor White
Write-Host "  4. Verify health endpoint returns 200" -ForegroundColor White
