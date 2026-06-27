@echo off
setlocal enabledelayedexpansion
title Herald MCP - Setup
cd /d "%~dp0"

echo ============================================
echo  Herald MCP Setup
echo ============================================
echo.

echo [0/4] Checking config.json...
if not exist "%~dp0config.json" (
    echo   config.json not found. Creating one now.
    echo.
    set /p SERVER_URL="  Enter Herald server URL (e.g. http://202.59.9.164:7700): "
    set /p PEER_NAME="  Enter a name for this machine (e.g. machine-b): "
    python -c "import json,sys; cfg={'name':sys.argv[1],'server_url':sys.argv[2],'peers':['machine-a']}; open(sys.argv[3],'w',encoding='utf-8').write(json.dumps(cfg,indent=2))" "!PEER_NAME!" "!SERVER_URL!" "%~dp0config.json"
    echo   [OK] config.json created.
) else (
    echo   [OK] config.json found.
)
echo.
echo [1/4] Installing Python dependencies...
pip install -r requirements.txt
pip install pystray pillow pywin32
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: pip install failed.
    echo Make sure Python 3.10+ is installed and added to PATH.
    pause
    exit /b 1
)

echo.
echo [1b/4] Installing windows-mcp (Claude Desktop remote control)...
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
echo [2/5] Registering with Claude Code...
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
echo [3/5] Registering with Antigravity...
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

python -c "import os; f=open(os.path.expandvars(r'%%TEMP%%\herald_mcp_register.py'), 'w', encoding='utf-8'); f.write('import sys, os, json\npaths = [os.path.expandvars(r\'%%USERPROFILE%%/.gemini/config/mcp_config.json\'), os.path.expandvars(r\'%%USERPROFILE%%/.gemini/antigravity/mcp_config.json\')]\nfor p in paths:\n    os.makedirs(os.path.dirname(p), exist_ok=True)\n    d = {}\n    if os.path.exists(p):\n        try:\n            with open(p, encoding=\'utf-8\') as f: d = json.load(f)\n        except: pass\n    if \'mcpServers\' not in d: d[\'mcpServers\'] = {}\n    d[\'mcpServers\'][\'herald\'] = {\'command\': \'python\', \'args\': [sys.argv[1]]}\n    with open(p, \'w\', encoding=\'utf-8\') as f: json.dump(d, f, indent=2)\n')"
python "%TEMP%\herald_mcp_register.py" "%~dp0mcp_server.py"
if exist "%TEMP%\herald_mcp_register.py" del "%TEMP%\herald_mcp_register.py"
if %ERRORLEVEL% neq 0 (
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
echo [4/5] Installing Herald tray daemon...
python "%~dp0herald_tray.py" --install
if %ERRORLEVEL% neq 0 (
    echo   WARNING: Could not install startup shortcut. Run manually:
    echo     python "%~dp0herald_tray.py" --install
) else (
    echo   [OK] Herald tray will start automatically at logon.
)

echo.
echo   Starting Herald tray now...
for /f "delims=" %%p in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do start "" "%%p" "%~dp0herald_tray.py"

echo.
echo ============================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Edit config.json -- fill in server_url and your machine name.
echo  2. Restart Claude Code (or Antigravity) to load the herald MCP.
echo  3. Look for the Herald icon in the system tray (bottom-right).
echo ============================================
echo.
pause
