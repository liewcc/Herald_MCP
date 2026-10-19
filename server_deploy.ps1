# Herald MCP - Server Deployment Script
# Run this in PowerShell on the cloud server (as Administrator)

$HERALD_DIR = "C:\Herald_MCP"
$PORT = 7700

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Herald MCP Server Deployment" -ForegroundColor Cyan
Write-Host "============================================"
Write-Host ""

# [1/5] Check Python
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") { $python = $cmd; break }
    } catch {}
}
if (-not $python) {
    Write-Host "  Python not found. Installing via winget..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $python = "python"
}
Write-Host "  [OK] Using: $python" -ForegroundColor Green

# [2/5] Create directory and write server.py
Write-Host ""
Write-Host "[2/5] Creating Herald files in $HERALD_DIR ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $HERALD_DIR | Out-Null

# Deploy the repo's server.py (run this script from a checkout of the repo).
Copy-Item "$PSScriptRoot\server.py" "$HERALD_DIR\server.py" -Force

# Generate a shared token once. Every client config.json needs the same "token".
$cfgPath = "$HERALD_DIR\config.json"
$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{ name = "herald-server"; port = $PORT } }
if (-not $cfg.token) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $cfg | Add-Member -NotePropertyName token -NotePropertyValue (($bytes | ForEach-Object { $_.ToString("x2") }) -join "") -Force
    $cfg | ConvertTo-Json | Set-Content $cfgPath -Encoding UTF8
    Write-Host '  New shared token - copy it into every client config.json as "token":' -ForegroundColor Yellow
    Write-Host "    $($cfg.token)"
}

Write-Host "  [OK] Files created." -ForegroundColor Green

# [3/5] Install dependencies
Write-Host ""
Write-Host "[3/5] Installing Python dependencies..." -ForegroundColor Yellow
& $python -m pip install fastapi "uvicorn[standard]" httpx --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: pip install failed." -ForegroundColor Red; exit 1
}
Write-Host "  [OK] Dependencies installed." -ForegroundColor Green

# [4/5] Open firewall
Write-Host ""
Write-Host "[4/5] Opening firewall port $PORT ..." -ForegroundColor Yellow
netsh advfirewall firewall add rule name="Herald MCP" dir=in action=allow protocol=TCP localport=$PORT | Out-Null
Write-Host "  [OK] Firewall rule added." -ForegroundColor Green

# [5/5] Register as scheduled task (runs at startup)
Write-Host ""
Write-Host "[5/5] Registering Herald as startup task..." -ForegroundColor Yellow
$pythonPath = (& $python -c "import sys; print(sys.executable)")
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "$HERALD_DIR\server.py" -WorkingDirectory $HERALD_DIR
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartOnFailure -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Unregister-ScheduledTask -TaskName "HeraldMCP" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "HeraldMCP" -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName "HeraldMCP"
Write-Host "  [OK] Herald started and set to auto-start on boot." -ForegroundColor Green

# Verify
Start-Sleep -Seconds 3
try {
    $r = Invoke-RestMethod -Uri "http://localhost:$PORT/health" -TimeoutSec 5
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host " Herald is RUNNING on port $PORT" -ForegroundColor Green
    Write-Host " Status: $($r.status)  Name: $($r.name)" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "  WARNING: Could not verify. Check manually:" -ForegroundColor Yellow
    Write-Host "    python C:\Herald_MCP\server.py" -ForegroundColor Yellow
}
Write-Host ""
