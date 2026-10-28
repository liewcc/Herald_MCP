@echo off
setlocal enabledelayedexpansion
title Herald MCP - Setup
cd /d "%~dp0"
rem !HERE! not %~dp0 below: %~dp0 expands while a ( ) block is parsed, so a ")" in the path would end the block.
set "HERE=%~dp0"

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
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    for /f "delims=" %%v in ('python --version') do echo   ERROR: %%v is too old - Herald needs 3.10+. Install 3.12 from python.org so "python --version" shows it, then rerun.
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
python -m pip install -r "!HERE!requirements.txt"
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
python "!HERE!setup_wizard.py" %*
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
    echo     claude mcp add -s user herald -- "!PYEXE!" "!HERE!mcp_server.py"
    goto :register_antigravity
)

set "REGISTER_MCP="
set /p REGISTER_MCP="  Register herald with Claude Code now? (y/n): "
if /i not "%REGISTER_MCP%"=="y" (
    echo   Skipped. Run manually when ready:
    echo     claude mcp add -s user herald -- "!PYEXE!" "!HERE!mcp_server.py"
    goto :register_antigravity
)

rem Remove first so a rerun replaces an old entry (e.g. one pointing at another python) instead of failing.
call claude mcp remove -s user herald >nul 2>&1
call claude mcp add -s user herald -- "!PYEXE!" "!HERE!mcp_server.py"
if %ERRORLEVEL% neq 0 (
    echo   WARNING: Registration failed. Run manually:
    echo     claude mcp add -s user herald -- "!PYEXE!" "!HERE!mcp_server.py"
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
    echo   NOTE: Antigravity not found. If you install it later, run:
    echo     python "!HERE!setup_wizard.py" --antigravity register
    goto :done
)

python "!HERE!setup_wizard.py" --antigravity check >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] herald is already registered with Antigravity.
    goto :done
)

set "REGISTER_AGY="
set /p REGISTER_AGY="  Register herald with Antigravity now? (y/n): "
if /i not "%REGISTER_AGY%"=="y" (
    echo   Skipped. Run manually when ready: python "!HERE!setup_wizard.py" --antigravity register
    goto :done
)
python "!HERE!setup_wizard.py" --antigravity register
if errorlevel 1 echo   WARNING: Antigravity registration failed - see the line above.

:done
echo.
echo   Creating desktop shortcut...
python "!HERE!setup_wizard.py" --shortcut
if errorlevel 1 echo   WARNING: Could not create the desktop shortcut - Herald works without it.

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
rem ponytail: replaces PATH, so process-only entries (e.g. an activated venv) are dropped - don't run inside a venv.
for /f "delims=" %%p in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"') do set "PATH=%%p"
exit /b 0

:find_tailscale
set "TS="
for /f "delims=" %%t in ('where tailscale 2^>nul') do if not defined TS set "TS=%%t"
if not defined TS if exist "%ProgramFiles%\Tailscale\tailscale.exe" set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
exit /b 0
