@echo off
REM Runs unit tests, then hits every live vendor endpoint (needs API keys in .env)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo Run "run project.bat" first to create .venv & pause & exit /b 1 )
echo === Unit tests ===
".venv\Scripts\python.exe" -m pytest -q
echo.
echo === Live vendor API tests ===
".venv\Scripts\python.exe" -m scripts.test_apis --ws-seconds 30
pause
