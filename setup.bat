@echo off
setlocal enabledelayedexpansion
title Herald MCP - Setup
cd /d "%~dp0"

echo ============================================
echo  Herald MCP Setup
echo ============================================
echo.

echo Have these ready before you continue:
echo   - Is this PC hosting the relay for a NEW network, or JOINING an existing one?
echo   - Joining: the relay URL (http://^<relay Tailscale IP^>:7700) and its token.
echo   - Tailscale installed and logged in, and the relay PC visible in `tailscale status`.
echo.

echo [1/6] Checking Python...
rem A Microsoft Store alias stub makes "python --version" fail, which correctly triggers the install.
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   Python not found. Installing Python 3.12 via winget...
    rem --source winget skips the msstore source, whose terms prompt hangs non-interactive shells.
    winget install --id Python.Python.3.12 --source winget --scope user --accept-source-agreements --accept-package-agreements
    for /f "tokens=*" %%p in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','User')"') do set "PATH=%%p;!PATH!"
    python --version >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo   ERROR: Python install failed. Install Python 3.12 from python.org, reopen this window, rerun.
        pause
        exit /b 1
    )
)
echo   [OK] Python ready.

echo.
echo [2/6] Installing Python dependencies...
python -m pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo.
echo [3/6] Herald configuration wizard...
python "%~dp0setup_wizard.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo Wizard did not finish - nothing further was installed. Fix the issue above and rerun setup.bat.
    pause
    exit /b 1
)

echo.
echo [4/6] Installing windows-mcp (Claude Desktop remote control)...
pip show windows-mcp >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] windows-mcp already installed.
) else (
    pip install windows-mcp
    if %ERRORLEVEL% neq 0 (
        echo   WARNING: windows-mcp install failed. Desktop automation will not work.
        echo   Install manually later: pip install windows-mcp
    ) else (
        echo   [OK] windows-mcp installed.
    )
)

echo.
echo        Adding windows-mcp to .mcp.json...
python -c "
import json, os, sys
mcp_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), '.mcp.json')
d = {}
if os.path.exists(mcp_path):
    try:
        with open(mcp_path, encoding='utf-8') as f: d = json.load(f)
    except: pass
if 'mcpServers' not in d: d['mcpServers'] = {}
python_exe = sys.executable
if d['mcpServers'].get('windows-mcp'):
    print('  [OK] windows-mcp already in .mcp.json.')
else:
    d['mcpServers']['windows-mcp'] = {'command': python_exe, 'args': ['-m', 'windows_mcp', 'serve']}
    with open(mcp_path, 'w', encoding='utf-8') as f: json.dump(d, f, indent=4)
    print('  [OK] windows-mcp added to .mcp.json.')
" "%~dp0mcp_server.py"

echo.
echo [5/6] Registering with Claude Code...
where claude >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   WARNING: claude CLI not found in PATH.
    echo   Run this command manually after installing Claude Code:
    echo     claude mcp add herald -- python "%~dp0mcp_server.py"
    goto :register_antigravity
)

set /p REGISTER_MCP="  Register herald with Claude Code now? (y/n): "
if /i not "%REGISTER_MCP%"=="y" (
    echo   Skipped. Run manually when ready:
    echo     claude mcp add herald -- python "%~dp0mcp_server.py"
    goto :register_antigravity
)

claude mcp add herald -- python "%~dp0mcp_server.py"
if %ERRORLEVEL% neq 0 (
    echo   WARNING: Registration failed. Try running manually:
    echo     claude mcp add herald -- python "%~dp0mcp_server.py"
    goto :register_antigravity
)

echo.
echo   Verifying registration...
claude mcp list | findstr "herald" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] herald registered successfully with Claude Code.
) else (
    echo   WARNING: Could not verify. Check with: claude mcp list
)

:register_antigravity
echo.
echo [6/6] Registering with Antigravity...
set "AGY_FOUND="
if exist "%LOCALAPPDATA%\agy\bin\agy.exe"                              set "AGY_FOUND=1"
if exist "%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe"         set "AGY_FOUND=1"
if exist "%LOCALAPPDATA%\Programs\Antigravity IDE\Antigravity IDE.exe" set "AGY_FOUND=1"

if not defined AGY_FOUND (
    echo   NOTE: Antigravity not found. If you install it later, add this to:
    echo     %%USERPROFILE%%\.gemini\config\mcp_config.json
    echo     and %%USERPROFILE%%\.gemini\antigravity\mcp_config.json
    echo.
    echo   {
    echo     "mcpServers": {
    echo       "herald": {
    echo         "command": "python",
    echo         "args": ["PATH_TO_HERALD_MCP\mcp_server.py"]
    echo       }
    echo     }
    echo   }
    goto :done
echo.
echo   Creating desktop shortcut...
python -c "import sys,win32com.client,os; q=chr(34); d=os.path.join(os.path.expanduser('~'),'Desktop'); p=sys.argv[1]; ico=sys.argv[2]; lnk_path=os.path.join(d,'Herald MCP.lnk'); wsh=win32com.client.Dispatch('WScript.Shell'); s=wsh.CreateShortcut(lnk_path); s.TargetPath=sys.executable; s.Arguments=q+p+q; s.WorkingDirectory=os.path.dirname(p); s.IconLocation=ico; s.Description='Herald MCP Tray'; s.Save(); print('  [OK] Shortcut: '+lnk_path)" "%~dp0herald_tray.py" "%~dp0img\logo.ico"

echo.
echo ============================================
echo  Setup complete! The wizard already started Herald.
echo.
echo  Next steps:
echo  1. Restart Claude Code (or Antigravity) on PCs that control others.
echo  2. From the controlling PC, verify with exec_shell(peer_name, "hostname").
echo  3. Settings changed later? Rerun setup_wizard.py instead of editing config.json.
echo ============================================
echo.
pause
