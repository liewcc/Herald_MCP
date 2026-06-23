# Herald AutoRun Setup Script
# Run once on machine B to enable unattended herald polling via Windows Task Scheduler.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "=== Herald AutoRun Setup ===" -ForegroundColor Cyan

# --- 1. Project directory (script's own location) ---
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "[1] Project dir: $projectDir"

# --- 2. Find Python ---
$pythonPath = $null
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $pythonPath = $c; break }
}
if (-not $pythonPath) {
    $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $pythonPath) {
    Write-Host "[ERROR] Python not found. Install Python and retry." -ForegroundColor Red
    exit 1
}
Write-Host "[2] Python: $pythonPath"

# --- 3. Install pip dependencies ---
Write-Host "[3] Installing dependencies..."
& $pythonPath -m pip install httpx mcp fastmcp --quiet --disable-pip-version-check

# --- 4. Write .mcp.json with correct local paths ---
$mcpJson = @{
    mcpServers = @{
        herald = @{
            command = $pythonPath
            args    = @("$projectDir\mcp_server.py")
        }
    }
} | ConvertTo-Json -Depth 5
$mcpPath = "$projectDir\.mcp.json"
[System.IO.File]::WriteAllText($mcpPath, $mcpJson, [System.Text.Encoding]::UTF8)
Write-Host "[4] .mcp.json written: $mcpPath"

# --- 5. Find claude.exe ---
$claudeExe = $null
$claudeBase = "$env:APPDATA\Claude\claude-code"
if (Test-Path $claudeBase) {
    $latest = Get-ChildItem $claudeBase -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if ($latest) {
        $candidate = "$($latest.FullName)\claude.exe"
        if (Test-Path $candidate) { $claudeExe = $candidate }
    }
}
if (-not $claudeExe) {
    Write-Host "[ERROR] claude.exe not found under $claudeBase" -ForegroundColor Red
    exit 1
}
Write-Host "[5] claude.exe: $claudeExe"

# --- 6. Register scheduled task ---
$prompt = 'please use the herald MCP tool: call get_pending to check for messages, if any message exists call reply to respond, then exit'
$action   = New-ScheduledTaskAction -Execute $claudeExe `
    -Argument "-p `"$prompt`" --allowedTools `"mcp__herald__get_pending,mcp__herald__reply`"" `
    -WorkingDirectory $projectDir
$trigger  = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 1) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName "HeraldAutoReply" -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Highest -Force | Out-Null
} catch {
    # Fallback without elevated level if no admin rights
    Register-ScheduledTask -TaskName "HeraldAutoReply" -Action $action -Trigger $trigger `
        -Settings $settings -Force | Out-Null
}
Write-Host "[6] Scheduled task registered." -ForegroundColor Green

# --- 7. Verify ---
$task = Get-ScheduledTask -TaskName "HeraldAutoReply" -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "[7] Task state: $($task.State)" -ForegroundColor Green
} else {
    Write-Host "[7] ERROR: Task not found after registration." -ForegroundColor Red
    exit 1
}

# --- 8. Run once immediately to test ---
Write-Host "[8] Running task once to test..."
Start-ScheduledTask -TaskName "HeraldAutoReply"
Start-Sleep -Seconds 15
$info = Get-ScheduledTaskInfo -TaskName "HeraldAutoReply"
$result = $info.LastTaskResult
if ($result -eq 0) {
    Write-Host "[8] Test run succeeded (exit code 0)." -ForegroundColor Green
} else {
    Write-Host "[8] Test run exit code: $result (non-zero may indicate an issue)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host "HeraldAutoReply task will run every 1 minute automatically."
Write-Host "Project : $projectDir"
Write-Host "Python  : $pythonPath"
Write-Host "Claude  : $claudeExe"
