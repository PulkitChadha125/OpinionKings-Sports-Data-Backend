@echo off
REM OpinionKings sports data backend - one-click launcher
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating virtual environment .venv ...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 ( echo Failed to create .venv - install Python 3.11+ & pause & exit /b 1 )
)

echo [setup] installing requirements ...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 ( echo pip install failed & pause & exit /b 1 )

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [setup] created .env from .env.example - add ODDSPAPI_API_KEY and SPORTSDATAIO_API_KEY
)

echo.
echo  Backend:  http://localhost:8000
echo  Swagger:  http://localhost:8000/docs
echo  ReDoc:    http://localhost:8000/redoc
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
