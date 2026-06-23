@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo Welcome to the Herald MCP Network Setup Assistant
echo ===================================================
echo This helper script will install Tailscale and connect your
echo computer to the shared network.
echo.

:: Check for administrative privileges
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo =================================================================
    echo WARNING: Administrative privileges are required.
    echo.
    echo Please right-click this client.bat file and select "Run as administrator".
    echo =================================================================
    echo.
    pause
    exit /b 1
)

:: Step 1: Prompt for Tailscale Auth Key
echo === STEP 1: Enter your Auth Key ===
set /p "AUTH_KEY=Please paste the Tailscale auth key provided by Machine A's owner: "
if "%AUTH_KEY%"=="" (
    echo.
    echo ERROR: Auth Key cannot be empty. Please run this script again and enter the key.
    echo.
    pause
    exit /b 1
)

:: Check if Tailscale is already installed
where tailscale >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo Tailscale is already installed on this machine. Skipping installation step.
    goto connect
)

echo.
echo === STEP 2: Installing Tailscale ===
echo Installing Tailscale securely in the background...
echo (This may take a minute or two. Please wait...)
echo.

winget install --id tailscale.tailscale --silent --accept-package-agreements --accept-source-agreements
if %ERRORLEVEL% NEQ 0 (
    :: Double check if it was installed but path is not refreshed yet.
    if exist "%ProgramFiles%\Tailscale\tailscale.exe" (
        set "PATH=%PATH%;%ProgramFiles%\Tailscale"
        goto connect
    )
    echo.
    echo -----------------------------------------------------------------
    echo ERROR: Automatic installation using 'winget' failed.
    echo.
    echo Please follow these steps to install Tailscale manually:
    echo 1. Open your web browser and go to: https://tailscale.com/download/windows
    echo 2. Download and install Tailscale for Windows.
    echo 3. Once installed, re-run this script.
    echo -----------------------------------------------------------------
    echo.
    pause
    exit /b 1
)

echo.
echo === STEP 3: Initializing Tailscale ===
echo Tailscale installed successfully! Waiting 3 seconds for service startup...
timeout /t 3 /nobreak >nul

:: Update PATH in current session in case it was just installed
set "PATH=%PATH%;%ProgramFiles%\Tailscale"

:connect
echo.
echo === STEP 4: Connecting to the Herald MCP Network ===
echo Connecting...
tailscale up --authkey=%AUTH_KEY%
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Failed to connect to Tailscale using the provided key.
    echo Please check if the key is correct or expired, and try running this script again.
    echo.
    pause
    exit /b 1
)

echo.
echo === STEP 5: Getting your Tailscale IP Address ===
for /f "usebackq tokens=*" %%i in (`tailscale ip -4`) do set "TS_IP=%%i"

echo.
echo =================================================================
echo SUCCESS: You are connected to the network!
echo.
echo Your Tailscale IP is: %TS_IP%
echo.
echo == ACTION REQUIRED ==
echo Please copy and send this IP address (%TS_IP%) to Machine A's owner.
echo =================================================================
echo.

pause
