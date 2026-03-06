@echo off
REM Install Google USB Drivers for Pixel 3
REM This script installs the Android USB driver silently

echo Installing Google USB Drivers...

REM Check if driver INF exists
if exist "%~dp0usb_driver\android_winusb.inf" (
    pnputil /add-driver "%~dp0usb_driver\android_winusb.inf" /install
    echo Driver installation complete.
) else (
    echo USB driver files not found.
    echo Please download Google USB Drivers from:
    echo https://developer.android.com/studio/run/win-usb
    echo and extract to the drivers\usb_driver folder.
)

pause
