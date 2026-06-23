@echo off
title Herald MCP - Setup
cd /d "%~dp0"

echo ============================================
echo  Herald MCP Setup
echo ============================================
echo.

echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: pip install failed.
    echo Make sure Python 3.10+ is installed and added to PATH.
    pause
    exit /b 1
)

echo.
echo [2/3] Registering with Claude Code...
where claude >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   WARNING: claude CLI not found in PATH.
    echo   Run this command manually after installing Claude Code:
    echo     claude mcp add herald -- python "%~dp0run.py"
    goto :register_antigravity
)

set /p REGISTER_MCP="  Register herald with Claude Code now? (y/n): "
if /i not "%REGISTER_MCP%"=="y" (
    echo   Skipped. Run manually when ready:
    echo     claude mcp add herald -- python "%~dp0run.py"
    goto :register_antigravity
)

claude mcp add herald -- python "%~dp0run.py"
if %ERRORLEVEL% neq 0 (
    echo   WARNING: Registration failed. Try running manually:
    echo     claude mcp add herald -- python "%~dp0run.py"
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
echo [3/3] Registering with Antigravity...
set "AGY_FOUND="
if exist "%LOCALAPPDATA%\agy\bin\agy.exe"                              set "AGY_FOUND=1"
if exist "%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe"         set "AGY_FOUND=1"
if exist "%LOCALAPPDATA%\Programs\Antigravity IDE\Antigravity IDE.exe" set "AGY_FOUND=1"

if not defined AGY_FOUND (
    echo   NOTE: Antigravity not found. If you install it later, add this to:
    echo     %%USERPROFILE%%\.gemini\config\mcp_config.json
    echo.
    echo   {
    echo     "mcpServers": {
    echo       "herald": {
    echo         "command": "python",
    echo         "args": ["PATH_TO_HERALD_MCP\run.py"]
    echo       }
    echo     }
    echo   }
    goto :done
)

python -c "import json,os; p=os.path.expandvars(r'%%USERPROFILE%%/.gemini/config/mcp_config.json'); exit(0 if os.path.exists(p) and 'herald' in json.load(open(p,encoding='utf-8')).get('mcpServers',{}) else 1)" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] herald is already registered with Antigravity.
    goto :done
)

set /p REGISTER_AGY="  Register herald with Antigravity now? (y/n): "
if /i not "%REGISTER_AGY%"=="y" (
    echo   Skipped. Run manually when ready.
    goto :done
)

python -c "import os; f=open(os.path.expandvars(r'%%TEMP%%\herald_mcp_register.py'), 'w', encoding='utf-8'); f.write('import sys, os, json\np = os.path.expandvars(r\'%%USERPROFILE%%/.gemini/config/mcp_config.json\')\nos.makedirs(os.path.dirname(p), exist_ok=True)\nd = {}\nif os.path.exists(p):\n    try:\n        with open(p, encoding=\'utf-8\') as f: d = json.load(f)\n    except: pass\nif \'mcpServers\' not in d: d[\'mcpServers\'] = {}\nd[\'mcpServers\'][\'herald\'] = {\'command\': \'python\', \'args\': [sys.argv[1]]}\nwith open(p, \'w\', encoding=\'utf-8\') as f: json.dump(d, f, indent=2)\n')"
python "%TEMP%\herald_mcp_register.py" "%~dp0run.py"
if exist "%TEMP%\herald_mcp_register.py" del "%TEMP%\herald_mcp_register.py"
if %ERRORLEVEL% neq 0 (
    echo   WARNING: Could not write config. Check %%USERPROFILE%%\.gemini\config\mcp_config.json
    goto :done
)

python -c "import json,os; p=os.path.expandvars(r'%%USERPROFILE%%/.gemini/config/mcp_config.json'); exit(0 if os.path.exists(p) and 'herald' in json.load(open(p,encoding='utf-8')).get('mcpServers',{}) else 1)" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] herald registered successfully with Antigravity.
) else (
    echo   WARNING: Could not verify. Check %%USERPROFILE%%\.gemini\config\mcp_config.json
)

:done
echo.
echo ============================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Edit config.json — fill in your peer's Tailscale IP.
echo  2. Restart Claude Code (or Antigravity) to load the herald MCP.
echo  3. Ask Claude to call list_peers() to confirm Herald is working.
echo ============================================
echo.
pause
