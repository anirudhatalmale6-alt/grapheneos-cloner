# GrapheneOS Cloner

Windows desktop application for cloning Pixel 3 devices running GrapheneOS.

## Features

- **Create Image**: Capture full system image from master Pixel 3
- **Clone Device**: Flash image onto target devices (one-by-one or parallel)
- **App Selection**: Choose specific apps to include/exclude before cloning
- **Backup & Restore**: Full backup of user-installed apps
- **Modern GUI**: Dark-themed, no terminal windows needed

## Quick Start

1. Install Python 3.10+
2. `pip install -r requirements.txt`
3. Download [Android SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools) and put `adb.exe` + `fastboot.exe` in `tools/`
4. Run: `python main.py`

## Building Windows Installer

Run `build_windows.bat` — requires PyInstaller and optionally Inno Setup 6.

## Prerequisites

- USB Debugging enabled on master phone
- OEM Unlocking enabled on target phones
- Google USB Drivers installed (included in installer)
