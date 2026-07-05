@echo off
title PDF Font Processor Dashboard
cd /d "%~dp0"

:: Set the specific Python path that was verified on this system
set PYTHON_PATH="C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe"

if exist %PYTHON_PATH% (
    %PYTHON_PATH% process_inbox.py
) else (
    echo [Warning] Custom Python path not found. Trying default python/py command...
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        python process_inbox.py
    ) else (
        where py >nul 2>nul
        if %errorlevel% equ 0 (
            py process_inbox.py
        ) else (
            echo [Error] Python is not installed or not in PATH.
            echo Please install Python 3.10+ and try again.
            pause
        )
    )
)
