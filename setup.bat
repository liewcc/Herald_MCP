@echo off
setlocal enabledelayedexpansion
title Herald MCP - Setup
cd /d "%~dp0"

rem "setup.bat --prereqs": only check/install git, Python, Tailscale and pip deps; never prompts (AI installers).
set "PREREQ_ONLY="
if /i "%~1"=="--prereqs" set "PREREQ_ONLY=1"
set "NOWINGET="
where winget >nul 2>&1 || set "NOWINGET=1"

echo ============================================
echo  Herald MCP Setup
echo ============================================
echo.
if not defined PREREQ_ONLY (
    echo Have these ready before you continue:
    echo   - Is this PC hosting the relay for a NEW network, or JOINING an existing one?
    echo   - Joining: the relay URL ^(http://^<relay Tailscale IP^>:7700^) and its token.
    echo   - The Tailscale account to log in with. Setup installs Tailscale if it is missing.
    echo.
)

echo [1/5] Checking prerequisites: git, Python, Tailscale...
where git >nul 2>&1
if errorlevel 1 call :install Git.Git "git"
where git >nul 2>&1 && (echo   [OK] git) || (echo   WARNING: git not found - Herald runs without it, it is only needed for updates.)

rem A Microsoft Store alias stub makes "python --version" fail, which correctly triggers the install.
python --version >nul 2>&1
if errorlevel 1 call :install Python.Python.3.12 "Python 3.12" --scope user
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python is still not available. Install Python 3.12 from python.org, reopen this window, rerun.
    if not defined PREREQ_ONLY pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo   [OK] %%v

call :find_tailscale
if not defined TS (
    echo   Tailscale installs machine-wide: approve the Windows admin prompt when it appears.
    call :install Tailscale.Tailscale "Tailscale"
    call :find_tailscale
)
if not defined TS (
    echo   WARNING: Tailscale not found. Install it from https://tailscale.com/download - PCs on different networks need it.
) else (
    call "!TS!" ip -4 >nul 2>&1
    if errorlevel 1 (
        if defined PREREQ_ONLY (
            echo   Tailscale is installed but not logged in - the user must log in: tray icon, Log in.
        ) else (
            echo   Log in to Tailscale: a sign-in page opens - sign in, then come back to this window.
            call "!TS!" up
        )
    )
    for /f "delims=" %%i in ('call "!TS!" ip -4 2^>nul') do echo   [OK] Tailscale: this PC is %%i
)

echo.
echo [2/5] Installing Python dependencies...
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed.
    if not defined PREREQ_ONLY pause
    exit /b 1
)
if defined PREREQ_ONLY (
    echo.
    echo [OK] Prerequisites ready. Next: python setup_wizard.py with flags - see CLAUDE.md.
    exit /b 0
)

echo.
echo [3/5] Herald configuration wizard...
rem Any arguments (e.g. --role join --name pc2 --server-url ... --token ... --yes) go to the wizard.
python "%~dp0setup_wizard.py" %*
if %ERRORLEVEL% neq 0 (
    echo.
    echo Wizard did not finish - nothing further was installed. Fix the issue above and rerun setup.bat.
    pause
    exit /b 1
)

echo.
echo [4/5] Registering with Claude Code...
rem Register the exact interpreter that has Herald's deps - a bare "python" may be another install.
for /f "delims=" %%e in ('python -c "import sys; print(sys.executable)"') do set "PYEXE=%%e"
where claude >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   WARNING: claude CLI not found in PATH.
    echo   Run this command manually after installing Claude Code:
    echo     claude mcp add herald -- "!PYEXE!" "%~dp0mcp_server.py"
    goto :register_antigravity
)

set /p REGISTER_MCP="  Register herald with Claude Code now? (y/n): "
if /i not "%REGISTER_MCP%"=="y" (
    echo   Skipped. Run manually when ready:
    echo     claude mcp add herald -- "!PYEXE!" "%~dp0mcp_server.py"
    goto :register_antigravity
)

call claude mcp add herald -- "!PYEXE!" "%~dp0mcp_server.py"
if %ERRORLEVEL% neq 0 (
    echo   WARNING: Registration failed. Try running manually:
    echo     claude mcp add herald -- "!PYEXE!" "%~dp0mcp_server.py"
    goto :register_antigravity
)

echo.
echo   Verifying registration...
call claude mcp list | findstr "herald" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] herald registered successfully with Claude Code.
) else (
    echo   WARNING: Could not verify. Check with: claude mcp list
)

:register_antigravity
echo.
echo [5/5] Registering with Antigravity...
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
)

python -c "import json,os; paths=[os.path.expandvars(r'%%USERPROFILE%%/.gemini/config/mcp_config.json'), os.path.expandvars(r'%%USERPROFILE%%/.gemini/antigravity/mcp_config.json')]; exit(0 if all(os.path.exists(p) and 'herald' in json.load(open(p,encoding='utf-8')).get('mcpServers',{}) for p in paths) else 1)" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] herald is already registered with Antigravity.
    goto :done
)

set /p REGISTER_AGY="  Register herald with Antigravity now? (y/n): "
if /i not "%REGISTER_AGY%"=="y" (
    echo   Skipped. Run manually when ready.
    goto :done
)

python -c "import os; f=open(os.path.expandvars(r'%%TEMP%%\herald_mcp_register.py'), 'w', encoding='utf-8'); f.write('import sys, os, json\npaths = [os.path.expandvars(r\'%%USERPROFILE%%/.gemini/config/mcp_config.json\'), os.path.expandvars(r\'%%USERPROFILE%%/.gemini/antigravity/mcp_config.json\')]\nfor p in paths:\n    os.makedirs(os.path.dirname(p), exist_ok=True)\n    d = {}\n    if os.path.exists(p):\n        try:\n            with open(p, encoding=\'utf-8\') as f: d = json.load(f)\n        except: pass\n    if \'mcpServers\' not in d: d[\'mcpServers\'] = {}\n    d[\'mcpServers\'][\'herald\'] = {\'command\': sys.executable, \'args\': [sys.argv[1]]}\n    with open(p, \'w\', encoding=\'utf-8\') as f: json.dump(d, f, indent=2)\n')"
python "%TEMP%\herald_mcp_register.py" "%~dp0mcp_server.py"
set "REG_RC=%ERRORLEVEL%"
if exist "%TEMP%\herald_mcp_register.py" del "%TEMP%\herald_mcp_register.py"
if not "%REG_RC%"=="0" (
    echo   WARNING: Could not write config. Check %%USERPROFILE%%\.gemini\config\mcp_config.json and %%USERPROFILE%%\.gemini\antigravity\mcp_config.json
    goto :done
)

python -c "import json,os; paths=[os.path.expandvars(r'%%USERPROFILE%%/.gemini/config/mcp_config.json'), os.path.expandvars(r'%%USERPROFILE%%/.gemini/antigravity/mcp_config.json')]; exit(0 if all(os.path.exists(p) and 'herald' in json.load(open(p,encoding='utf-8')).get('mcpServers',{}) for p in paths) else 1)" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] herald registered successfully with Antigravity.
) else (
    echo   WARNING: Could not verify. Check %%USERPROFILE%%\.gemini\config\mcp_config.json and %%USERPROFILE%%\.gemini\antigravity\mcp_config.json
)

:done
echo.
echo   Creating desktop shortcut...
python -c "import sys,win32com.client,os; q=chr(34); d=os.path.join(os.path.expanduser('~'),'Desktop'); p=sys.argv[1]; ico=sys.argv[2]; lnk_path=os.path.join(d,'Herald MCP.lnk'); wsh=win32com.client.Dispatch('WScript.Shell'); s=wsh.CreateShortcut(lnk_path); s.TargetPath=sys.executable; s.Arguments=q+p+q; s.WorkingDirectory=os.path.dirname(p); s.IconLocation=ico; s.Description='Herald MCP Tray'; s.Save(); print('  [OK] Shortcut: '+lnk_path)" "%~dp0herald_tray.py" "%~dp0img\logo.ico"

echo.
echo ============================================
echo  Setup complete. The wizard already started Herald.
echo.
echo  Next steps:
echo  1. Restart Claude Code (or Antigravity) on PCs that control others.
echo  2. From the controlling PC, verify with exec_shell(peer_name, "hostname").
echo  3. Settings changed later? Rerun setup_wizard.py instead of editing config.json.
echo ============================================
echo.
pause
exit /b 0

:install
rem %1 = winget id, %2 = name to show, %3 %4 = extra winget args.
rem --source winget skips the msstore source, whose terms prompt hangs non-interactive shells.
if defined NOWINGET (
    echo   %~2 not found and winget is unavailable - install %~2 manually, then rerun.
    exit /b 1
)
echo   %~2 not found. Installing via winget...
call winget install --id %1 --source winget --accept-source-agreements --accept-package-agreements %3 %4
call :refresh_path
exit /b 0

:refresh_path
rem winget updates the PATH in the registry, not in this window; reload it so new tools are found.
for /f "delims=" %%p in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"') do set "PATH=%%p"
exit /b 0

:find_tailscale
set "TS="
for /f "delims=" %%t in ('where tailscale 2^>nul') do if not defined TS set "TS=%%t"
if not defined TS if exist "%ProgramFiles%\Tailscale\tailscale.exe" set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
exit /b 0
