@echo off
echo === SI Quote Agent Installer ===
echo.

:: Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.12+ from python.org
    pause
    exit /b 1
)

:: Install requests if needed
pip show requests >nul 2>nul
if %errorlevel% neq 0 (
    echo Installing required package: requests
    pip install requests
)

:: Run setup if no config exists
if not exist "%~dp0config.json" (
    echo No config found. Running first-time setup...
    echo.
    python "%~dp0si_quote_agent.py" --setup
    echo.
)

:: Create Windows Scheduled Task
echo Creating scheduled task "SI Quote Agent"...
schtasks /create /tn "SI Quote Agent" /tr "pythonw \"%~dp0si_quote_agent.py\" --daemon" /sc onlogon /rl highest /f
if %errorlevel% equ 0 (
    echo.
    echo SUCCESS: SI Quote Agent will start automatically on login.
    echo.
    echo To start it now, run:
    echo   python "%~dp0si_quote_agent.py" --daemon
    echo.
    echo To check logs:
    echo   type "%~dp0agent.log"
    echo.
    echo To stop the scheduled task:
    echo   schtasks /delete /tn "SI Quote Agent" /f
) else (
    echo.
    echo Could not create scheduled task. You can run manually:
    echo   python "%~dp0si_quote_agent.py" --daemon
)

echo.
pause
