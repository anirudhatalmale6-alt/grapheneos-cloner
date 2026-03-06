@echo off
REM =============================================
REM  GrapheneOS Cloner - Windows Build Script
REM =============================================
REM
REM Prerequisites:
REM   1. Python 3.10+ installed
REM   2. pip install -r requirements.txt
REM   3. Inno Setup 6 installed (for installer)
REM   4. adb.exe + fastboot.exe in tools/ folder
REM      (Download from https://developer.android.com/tools/releases/platform-tools)
REM   5. Google USB Driver in drivers/usb_driver/ folder
REM      (Download from https://developer.android.com/studio/run/win-usb)
REM
REM =============================================

echo.
echo ========================================
echo  GrapheneOS Cloner - Build
echo ========================================
echo.

REM Step 1: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

REM Step 2: Install dependencies
echo [1/4] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Step 3: Check for adb/fastboot
if not exist "tools\adb.exe" (
    echo WARNING: tools\adb.exe not found!
    echo Download Android SDK Platform Tools and copy adb.exe + fastboot.exe to the tools\ folder.
    echo https://developer.android.com/tools/releases/platform-tools
    echo.
    echo Press any key to continue anyway...
    pause >nul
)

REM Step 4: Build with PyInstaller
echo [2/4] Building executable with PyInstaller...
pyinstaller --clean build.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)

echo [3/4] Build complete! Output in dist\GrapheneOS_Cloner\
echo.

REM Step 5: Build installer (if Inno Setup is available)
where iscc >nul 2>&1
if not errorlevel 1 (
    echo [4/4] Building installer with Inno Setup...
    iscc installer.iss
    if errorlevel 1 (
        echo WARNING: Installer build failed
    ) else (
        echo Installer created in installer_output\
    )
) else (
    echo [4/4] Inno Setup not found - skipping installer creation.
    echo Install Inno Setup 6 from https://jrsoftware.org/isdownload.php
    echo Then run: iscc installer.iss
)

echo.
echo ========================================
echo  Build Complete!
echo ========================================
echo.
echo To run: dist\GrapheneOS_Cloner\GrapheneOS_Cloner.exe
echo.
pause
