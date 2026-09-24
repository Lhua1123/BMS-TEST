@echo off
cd /d "%~dp0"

set PYTHON=
if exist "D:\programfiles\python312\python.exe" (
    set "PYTHON=D:\programfiles\python312\python.exe"
)
if not defined PYTHON (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PYTHON set "PYTHON=%%i"
    )
)
if not defined PYTHON (
    echo [ERROR] Python not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

echo Using Python: %PYTHON%
"%PYTHON%" main.py
pause