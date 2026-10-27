@echo off
rem Ejecuta translateML con el entorno de .venv (crealo antes con setup.cmd).
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo Falta el entorno .venv. Ejecuta primero: %ROOT%setup.cmd 1>&2
    exit /b 2
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%ROOT%.venv\Scripts\python.exe" -B -m translateml %*
exit /b %ERRORLEVEL%
