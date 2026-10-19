@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0src;%PYTHONPATH%

echo ============================================================
echo  track400   default: 5 km @ 3'10"/km  (about 15m50s)
echo  lane 2 - stop/Ctrl+C restores the real location
echo ============================================================
echo  keys:  p = pause    r = resume    s = stop
echo.

python -m track400 %*
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" echo [OK] finished, real location restored.
if "%RC%"=="130" echo [STOPPED] real location restored.
if not "%RC%"=="0" if not "%RC%"=="130" echo [ERROR] exit code %RC% -- see docs\errors.md
echo.
pause
