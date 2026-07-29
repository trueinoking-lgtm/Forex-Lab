# Kronos V3 D1 Metadata Bridge — Windows deployment

Bridge version: `2026.07.29-d1-metadata.1`

Package SHA-256:
`727c372a8d40595e9e45d93cc781402e04779831f47841c118c1b8e9fb46cbc9`

Deployment has not occurred. Kade must run these commands in PowerShell on the
Windows bridge host. The existing `.env` is deliberately neither packaged nor
replaced.

## Backup, install, and restart

```powershell
$Package = "$env:USERPROFILE\Downloads\kronos_v3_bridge_2026.07.29-d1-metadata.1.zip"
$BridgeDir = "C:\Aether\remote-mt5-bridge"
$Stamp = Get-Date -Format "yyyyMMddTHHmmss"
$BackupDir = "C:\Aether\remote-mt5-bridge.backup-$Stamp"
$StageDir = "C:\Aether\remote-mt5-bridge.stage-$Stamp"

$ActualPackageHash = (Get-FileHash -Algorithm SHA256 $Package).Hash.ToLower()
if ($ActualPackageHash -ne "727c372a8d40595e9e45d93cc781402e04779831f47841c118c1b8e9fb46cbc9") {
    throw "Deployment package SHA-256 mismatch"
}

Copy-Item -LiteralPath $BridgeDir -Destination $BackupDir -Recurse
New-Item -ItemType Directory -Path $StageDir | Out-Null
Expand-Archive -LiteralPath $Package -DestinationPath $StageDir

$BridgeProcesses = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -like "*$BridgeDir\server.py*"
    }
$BridgeProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Copy-Item -LiteralPath "$StageDir\server.py" -Destination "$BridgeDir\server.py" -Force
Copy-Item -LiteralPath "$StageDir\bridge_validation.py" -Destination "$BridgeDir\bridge_validation.py" -Force
Copy-Item -LiteralPath "$StageDir\requirements.txt" -Destination "$BridgeDir\requirements.txt" -Force
Copy-Item -LiteralPath "$StageDir\BRIDGE_VERSION.txt" -Destination "$BridgeDir\BRIDGE_VERSION.txt" -Force

& "$BridgeDir\.venv\Scripts\python.exe" -m pip install -r "$BridgeDir\requirements.txt"
Start-Process `
    -FilePath "$BridgeDir\.venv\Scripts\python.exe" `
    -ArgumentList "`"$BridgeDir\server.py`"" `
    -WorkingDirectory $BridgeDir `
    -RedirectStandardOutput "$BridgeDir\bridge.stdout.log" `
    -RedirectStandardError "$BridgeDir\bridge.stderr.log"
```

## Endpoint verification

```powershell
$BridgeToken = Read-Host "Bridge bearer token"
$Headers = @{ Authorization = "Bearer $BridgeToken" }
$Health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8787/health"
$Metadata = Invoke-RestMethod `
    -Method Get `
    -Headers $Headers `
    -Uri "http://127.0.0.1:8787/d1-metadata?symbol=EURUSD&count=2"

if ($Health.bridge_version -ne "2026.07.29-d1-metadata.1") {
    throw "Wrong bridge version"
}
if ($Metadata.timeframe -ne "D1" -or $Metadata.ohlc_included -ne $false) {
    throw "D1 metadata contract failed"
}
$Metadata | ConvertTo-Json -Depth 4
```

## Rollback

Use the exact `$BackupDir` printed/retained from the install step.

```powershell
$BridgeDir = "C:\Aether\remote-mt5-bridge"
$BackupDir = "C:\Aether\remote-mt5-bridge.backup-REPLACE_WITH_INSTALL_STAMP"

$BridgeProcesses = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -like "*$BridgeDir\server.py*"
    }
$BridgeProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Copy-Item -LiteralPath "$BackupDir\server.py" -Destination "$BridgeDir\server.py" -Force
Copy-Item -LiteralPath "$BackupDir\bridge_validation.py" -Destination "$BridgeDir\bridge_validation.py" -Force
Copy-Item -LiteralPath "$BackupDir\requirements.txt" -Destination "$BridgeDir\requirements.txt" -Force
if (Test-Path "$BackupDir\BRIDGE_VERSION.txt") {
    Copy-Item -LiteralPath "$BackupDir\BRIDGE_VERSION.txt" -Destination "$BridgeDir\BRIDGE_VERSION.txt" -Force
} else {
    Remove-Item -LiteralPath "$BridgeDir\BRIDGE_VERSION.txt" -ErrorAction SilentlyContinue
}

& "$BridgeDir\.venv\Scripts\python.exe" -m pip install -r "$BridgeDir\requirements.txt"
Start-Process `
    -FilePath "$BridgeDir\.venv\Scripts\python.exe" `
    -ArgumentList "`"$BridgeDir\server.py`"" `
    -WorkingDirectory $BridgeDir `
    -RedirectStandardOutput "$BridgeDir\bridge.stdout.log" `
    -RedirectStandardError "$BridgeDir\bridge.stderr.log"
```
