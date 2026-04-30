@echo off
REM ai_loop.bat — launcher for the "AIM AI" Desktop icon on Windows.
REM Calls the standalone ai_loop.py so stdin stays bound to the terminal.

cd /d "%~dp0..\.."
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat
python scripts\desktop\ai_loop.py
echo.
pause
