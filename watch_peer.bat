@echo off
title Herald - Waiting for peer connection...
cd /d "%~dp0"

set PEER=machine-b
set INTERVAL=5

echo ============================================
echo  Watching for Tailscale peer: %PEER%
echo  Checking every %INTERVAL% seconds...
echo  Press Ctrl+C to stop.
echo ============================================
echo.

:loop
tailscale status 2>nul | findstr /i "%PEER%" >nul
if %ERRORLEVEL% equ 0 (
    echo [%TIME%] SUCCESS: %PEER% is connected!
    echo.
    tailscale status
    echo.
    echo ============================================
    echo  Peer is online. You can now run:
    echo    python cli.py ping %PEER%
    echo ============================================
    pause
    exit /b 0
) else (
    echo [%TIME%] Waiting... %PEER% not yet connected.
)

timeout /t %INTERVAL% /nobreak >nul
goto :loop
