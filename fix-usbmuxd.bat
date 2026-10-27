@echo off
setlocal

net session >nul 2>&1
if %errorlevel%==0 goto :run

echo Requesting administrator privileges (UAC)...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
echo ============================================================
echo  Repairing Apple Mobile Device Service (usbmuxd)
echo ============================================================
echo.

echo [1/3] Set StartupType = Automatic and start the service
sc config "Apple Mobile Device Service" start= auto >nul 2>&1
sc start "Apple Mobile Device Service" >nul 2>&1
timeout /t 2 >nul

echo [2/3] Service state:
sc query "Apple Mobile Device Service" | findstr /i "STATE"

echo.
echo [3/3] Devices seen by usbmuxd:
python -m pymobiledevice3 usbmux list
if errorlevel 1 (
  echo.
  echo Still failing. Try: unplug/replug the cable, or reinstall Apple Mobile Device Support.
)

echo.
pause
