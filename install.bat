@echo off
setlocal enabledelayedexpansion
title Herald MCP - Installation
cd /d "%~dp0"

:: ── Step 1: Popup — ask for server URL ──────────────────────────────────────
> "%TEMP%\herald_ask.vbs" echo Set oShell = CreateObject("WScript.Shell")
>> "%TEMP%\herald_ask.vbs" echo url = InputBox("Please paste the Herald server address" & Chr(10) & "provided by your network administrator:", "Herald MCP Setup", "http://")
>> "%TEMP%\herald_ask.vbs" echo WScript.Echo url

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
set "MACHINE_NAME=%COMPUTERNAME%"
for %%i in (A B C D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    set "MACHINE_NAME=!MACHINE_NAME:%%i=%%i!"
)
:: Use lowercase computer name, fallback to machine-b
powershell -NoProfile -Command "$name = $env:COMPUTERNAME.ToLower(); $cfg = [ordered]@{ name=$name; server_url='!SERVER_URL!'; peers=@('machine-a') }; $cfg | ConvertTo-Json | Set-Content '%~dp0config.json' -Encoding UTF8"
echo   [OK] config.json created (name: %COMPUTERNAME%).

:: ── Step 5: Register MCP ─────────────────────────────────────────────────────
echo.
echo [4/4] Registering Herald with Claude Code...
where claude >nul 2>&1
if %ERRORLEVEL% equ 0 (
    claude mcp add herald -- python "%~dp0run.py" >nul 2>&1
    echo   [OK] Registered with Claude Code.
) else (
    echo   NOTE: Claude Code not found - skipping MCP registration.
    echo   Run manually later: claude mcp add herald -- python "%~dp0run.py"
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
> "%TEMP%\herald_done.vbs" echo MsgBox "Herald MCP installed successfully!" & Chr(10) & Chr(10) & "Next step: restart Claude Code or Antigravity," & Chr(10) & "then ask Claude to call list_peers() to verify.", 64, "Herald MCP - Done"
cscript //nologo "%TEMP%\herald_done.vbs"
del "%TEMP%\herald_done.vbs" >nul 2>&1
