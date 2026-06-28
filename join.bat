@echo off
setlocal enabledelayedexpansion
title Herald MCP - Installation
cd /d "%~dp0"

:: ── Step 1: Popup — ask for server URL ──────────────────────────────────────
(
echo Set oShell = CreateObject^("WScript.Shell"^)
echo url = InputBox^("Please paste the Herald server address" ^& Chr^(10^) ^& "provided by your network administrator:", "Herald MCP Setup", "http://"^)
echo WScript.Echo url
) > "%TEMP%\herald_ask.vbs"

for /f "delims=" %%i in ('cscript //nologo "%TEMP%\herald_ask.vbs"') do set "SERVER_URL=%%i"
del "%TEMP%\herald_ask.vbs" >nul 2>&1

if "!SERVER_URL!"=="" (
    echo Setup cancelled.
    pause
    exit /b 0
)

echo.
echo ============================================
echo  Herald MCP Setup
echo  Server: !SERVER_URL!
echo ============================================
echo.

:: ── Step 2: Check / install Python ──────────────────────────────────────────
echo [1/4] Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   Python not found. Downloading installer...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe' -OutFile '%TEMP%\py_setup.exe'"
    echo   Installing Python (this may take a minute)...
    start /wait "" "%TEMP%\py_setup.exe" /quiet InstallAllUsers=0 PrependPath=1
    del "%TEMP%\py_setup.exe" >nul 2>&1
    :: Refresh PATH
    for /f "tokens=*" %%p in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"Path\",\"User\")"') do set "PATH=%%p;%PATH%"
    python --version >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo   ERROR: Python installation failed. Please install Python 3.12 manually from python.org
        pause
        exit /b 1
    )
)
echo   [OK] Python ready.

:: ── Step 3: Install dependencies ────────────────────────────────────────────
echo.
echo [2/4] Installing dependencies...
python -m pip install -r "%~dp0requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo   ERROR: pip install failed.
    pause
    exit /b 1
)
echo   [OK] Dependencies installed.

:: ── Step 4: Write config.json ────────────────────────────────────────────────
echo.
echo [3/4] Writing config.json...
python -c "import json,os,sys; cfg={'name':os.environ['COMPUTERNAME'].lower(),'server_url':sys.argv[1],'peers':['machine-a']}; open(sys.argv[2],'w',encoding='utf-8').write(json.dumps(cfg,indent=2))" "!SERVER_URL!" "%~dp0config.json"
if %ERRORLEVEL% neq 0 (
    echo   ERROR: Failed to write config.json.
    pause
    exit /b 1
)
echo   [OK] config.json created (name: %COMPUTERNAME%).

:: ── Step 5: Register MCP ─────────────────────────────────────────────────────
echo.
echo [4/4] Registering Herald with Claude Code...
where claude >nul 2>&1
if %ERRORLEVEL% equ 0 (
    claude mcp add herald -- python "%~dp0mcp_server.py" >nul 2>&1
    echo   [OK] Registered with Claude Code.
) else (
    echo   NOTE: Claude Code not found - skipping MCP registration.
    echo   Run manually later: claude mcp add herald -- python "%~dp0mcp_server.py"
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo   Creating desktop shortcut...
python -c "import sys,win32com.client,os; q=chr(34); d=os.path.join(os.path.expanduser('~'),'Desktop'); p=sys.argv[1]; ico=sys.argv[2]; lnk_path=os.path.join(d,'Herald MCP.lnk'); wsh=win32com.client.Dispatch('WScript.Shell'); s=wsh.CreateShortcut(lnk_path); s.TargetPath=sys.executable; s.Arguments=q+p+q; s.WorkingDirectory=os.path.dirname(p); s.IconLocation=ico; s.Description='Herald MCP Tray'; s.Save(); print('  [OK] Shortcut: '+lnk_path)" "%~dp0herald_tray.py" "%~dp0img\logo.ico"
echo.
(
echo MsgBox "Herald MCP installed successfully!" ^& Chr^(10^) ^& Chr^(10^) ^& "Next step: restart Claude Code or Antigravity," ^& Chr^(10^) ^& "then ask Claude to call list_peers^(^) to verify.", 64, "Herald MCP - Done"
) > "%TEMP%\herald_done.vbs"
cscript //nologo "%TEMP%\herald_done.vbs"
del "%TEMP%\herald_done.vbs" >nul 2>&1
