@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 gui.py %*
) else (
  python gui.py %*
)
if errorlevel 1 pause
