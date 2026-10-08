@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (python scripts\launch.py --stop) else (py -3 scripts\launch.py --stop)
if errorlevel 1 pause
