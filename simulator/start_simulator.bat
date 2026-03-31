@echo off
echo ========================================
echo   Vendor Quote Simulator
echo ========================================
echo.
echo [1/2] Starting PowerShell SMTP Relay on port 2525...
start "SMTP Relay" powershell -ExecutionPolicy Bypass -File "%~dp0smtp_relay.ps1"
timeout /t 2 /nobreak >nul
echo [2/2] Starting Vendor Simulator on http://localhost:8100 ...
echo.
echo Open http://localhost:8100 in your browser
echo Press Ctrl+C to stop
echo.
cd /d "%~dp0vendor_app"
python -m uvicorn main:app --host 0.0.0.0 --port 8100
