@echo off
rem Prepara translateML en Windows: crea .venv e instala el programa y openpyxl.
setlocal
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 'Se necesita Python 3.9 o superior.')" || goto :error
if not exist ".venv\Scripts\python.exe" (%PY% -m venv .venv || goto :error)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto :error
".venv\Scripts\python.exe" -m pip install --quiet -e . || goto :error
".venv\Scripts\python.exe" -m translateml --version || goto :error
echo Listo. Usa translateml.cmd (por ejemplo: translateml.cmd generate RUTA\eng\info\info.json --xlsx Multidioma.xlsx)
exit /b 0
:error
echo No se pudo preparar translateML. Revisa el mensaje anterior.
exit /b 1
