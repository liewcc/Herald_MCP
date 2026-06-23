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

@'
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from typing import List, Any, Optional
import uvicorn, asyncio, datetime

app = FastAPI(title="Herald MCP Hub")
pending_messages: dict = {}
reply_events: dict = {}

class AskBody(BaseModel):
    message_id: str
    from_peer: str
    to_peer: str = ""
    message: str
    attachments: List[Any] = []

class ReplyBody(BaseModel):
    answer: str
    attachments: List[Any] = []

async def check_disconnect(request: Request, message_id: str):
    try:
        while True:
            if await request.is_disconnected():
                pending_messages.pop(message_id, None)
                reply_events.pop(message_id, None)
                break
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass

@app.post("/ask")
async def ask(request: Request, body: AskBody):
    message_id = body.message_id
    pending_messages[message_id] = {
        "message_id": message_id,
        "from_peer": body.from_peer,
        "to_peer": body.to_peer,
        "message": body.message,
        "attachments": body.attachments,
        "received_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    event = asyncio.Event()
    reply_events[message_id] = (event, None)
    disconnect_task = asyncio.create_task(check_disconnect(request, message_id))
    try:
        await asyncio.wait_for(event.wait(), timeout=300.0)
        _, reply_data = reply_events.get(message_id, (None, None))
        return reply_data if reply_data else {"answer": "", "attachments": []}
    except asyncio.TimeoutError:
        return {"error": "timeout"}
    finally:
        disconnect_task.cancel()
        pending_messages.pop(message_id, None)
        reply_events.pop(message_id, None)

@app.post("/reply/{message_id}")
async def reply(message_id: str, body: ReplyBody):
    if message_id not in reply_events:
        raise HTTPException(status_code=404, detail="Message ID not found")
    event, _ = reply_events[message_id]
    reply_events[message_id] = (event, {"answer": body.answer, "attachments": body.attachments})
    event.set()
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok", "name": "herald-server", "version": "1.0"}

@app.get("/pending")
async def get_pending(peer: str = ""):
    msgs = list(pending_messages.values())
    if peer:
        msgs = [m for m in msgs if m.get("to_peer") == peer]
    return msgs

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7700)
'@ | Set-Content "$HERALD_DIR\server.py" -Encoding UTF8

'{"name": "herald-server", "port": 7700}' | Set-Content "$HERALD_DIR\config.json" -Encoding UTF8

Write-Host "  [OK] Files created." -ForegroundColor Green

# [3/5] Install dependencies
Write-Host ""
Write-Host "[3/5] Installing Python dependencies..." -ForegroundColor Yellow
& $python -m pip install fastapi "uvicorn[standard]" --quiet
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
