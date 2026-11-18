@echo off
rem Double-click to run CloudPeel on Windows. Close the window to stop it.
cd /d "%~dp0"
set PORT=8765
echo CloudPeel is running at http://localhost:%PORT%
echo Close this window to stop it.
start "" cmd /c "timeout /t 2 >nul & start http://localhost:%PORT%"
python -m http.server %PORT% --bind 127.0.0.1 -d site || py -m http.server %PORT% --bind 127.0.0.1 -d site
pause
