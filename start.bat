@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "PYTHON=%BACKEND%\.venv\python.exe"

if not exist "%PYTHON%" (
    echo Conda environment not found: %PYTHON%
    echo Create it with: conda create -p "%BACKEND%\.venv" python=3.11 pip
    exit /b 1
)

set "PYTHONIOENCODING=utf-8"
set "FASTMCP_HOME=%ROOT%.fastmcp"

echo Starting Aide backend and MCP service...
start "Aide-Backend" /D "%BACKEND%" "%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port 8000

echo Starting Aide frontend...
start "Aide-Frontend" /D "%ROOT%ui" cmd /c "npm run dev"

echo Backend: http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:3000
echo API docs: http://127.0.0.1:8000/docs
