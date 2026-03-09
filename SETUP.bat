@echo off
title GrapheneOS Cloner - Setup
color 0A
echo.
echo ============================================
echo   GrapheneOS Cloner - One-Click Setup
echo ============================================
echo.

:: Check for Python
echo [1/4] Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: Python is not installed!
        echo.
        echo  Please install Python first:
        echo  1. Go to https://www.python.org/downloads/
        echo  2. Download Python 3.10 or newer
        echo  3. IMPORTANT: Check "Add Python to PATH" during install
        echo  4. After installing, run this SETUP.bat again
        echo.
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)
echo  OK - Python found

:: Install Python dependencies
echo.
echo [2/4] Installing Python dependencies...
%PYTHON% -m pip install --quiet --upgrade pip >nul 2>&1
%PYTHON% -m pip install --quiet PyQt5 >nul 2>&1
if %errorlevel% neq 0 (
    echo  WARNING: Could not install PyQt5 automatically.
    echo  Trying alternative method...
    %PYTHON% -m pip install PyQt5
)
echo  OK - Dependencies installed

:: Download platform-tools if not present
echo.
echo [3/4] Checking for ADB and Fastboot...
if exist "tools\adb.exe" (
    echo  OK - ADB found
) else (
    echo  Downloading Android Platform Tools...
    echo  Please wait, this may take a minute...
    powershell -Command "& { try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile 'platform-tools.zip' -UseBasicParsing; Expand-Archive -Path 'platform-tools.zip' -DestinationPath '.' -Force; Copy-Item 'platform-tools\adb.exe' 'tools\' -Force; Copy-Item 'platform-tools\fastboot.exe' 'tools\' -Force; Copy-Item 'platform-tools\AdbWinApi.dll' 'tools\' -Force; Copy-Item 'platform-tools\AdbWinUsbApi.dll' 'tools\' -Force; Remove-Item 'platform-tools.zip' -Force; Remove-Item 'platform-tools' -Recurse -Force; Write-Host '  OK - ADB and Fastboot downloaded' } catch { Write-Host '  ERROR: Could not download. Please download manually from:'; Write-Host '  https://developer.android.com/tools/releases/platform-tools'; Write-Host '  Extract and copy adb.exe + fastboot.exe to the tools folder' } }"
)

:: Install Google USB Driver
echo.
echo [4/4] Checking USB drivers...
echo  Note: If your phone is not detected, install Google USB Driver:
echo  https://developer.android.com/studio/run/win-usb
echo.

:: Create launcher shortcut
echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo  BEFORE RUNNING: Make sure your phone has:
echo   - USB Debugging enabled
echo     (Settings ^> About Phone ^> tap Build Number 7x)
echo     (Settings ^> System ^> Developer Options ^> USB Debugging ON)
echo   - Phone connected via USB cable
echo   - "Allow USB Debugging" prompt accepted on phone
echo.
echo  Starting GrapheneOS Cloner now...
echo.
timeout /t 3 >nul

%PYTHON% main.py
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Application failed to start.
    echo  Please check the error message above.
    echo.
    pause
)
