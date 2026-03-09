@echo off
title GrapheneOS Cloner
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo Python not found. Please run SETUP.bat first.
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

%PYTHON% main.py
if %errorlevel% neq 0 (
    echo.
    echo Application encountered an error. See message above.
    pause
)
