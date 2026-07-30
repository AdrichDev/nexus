@echo off
REM ============================================================
REM  nexus - DIAGNOSTICO: por que falla cada suite.
REM  Deja el detalle en data\logs\diagnostico.txt
REM ============================================================
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "OUT=data\logs\diagnostico.txt"
if not exist "data\logs" mkdir "data\logs"
> "%OUT%" echo === DIAGNOSTICO nexus  %date% %time% ===

echo.
echo ============ A) El archivo command.css ============
>> "%OUT%" echo.
>> "%OUT%" echo --- atributos de frontend\css\command.css ---
attrib "frontend\css\command.css"
attrib "frontend\css\command.css" >> "%OUT%" 2>&1
echo   Quitando solo-lectura / oculto / sistema...
attrib -r -h -s "frontend\css\command.css" >nul 2>&1
if exist "frontend\css\command.css.new" (
  echo   Aplicando command.css.new ...
  copy /y "frontend\css\command.css.new" "frontend\css\command.css" >nul 2>&1
  if errorlevel 1 (
    echo     [X] SIGUE bloqueado. Es Controlled Folder Access de Windows Defender.
    >> "%OUT%" echo command.css: SIGUE BLOQUEADO tras attrib -r
  ) else (
    del /q "frontend\css\command.css.new" >nul 2>&1
    echo     [OK] command.css actualizado.
    >> "%OUT%" echo command.css: APLICADO con attrib -r + copy
  )
) else (
  echo   No hay command.css.new pendiente.
  >> "%OUT%" echo command.css: no habia .new pendiente
)

echo.
echo ============ B) Detalle de cada suite ============
for %%S in (test_all test_routing test_verificaciones test_renovacion test_mejoras_v19 test_specs_v20 test_v21_fixes test_specs_v23 test_specs_v23_orq test_specs_v23_mem test_specs_v23_files test_specs_v23_ui test_engram test_hermes_engram) do (
  echo   %%S ...
  >> "%OUT%" echo.
  >> "%OUT%" echo ===== %%S =====
  "%PY%" "tests\%%S.py" 2>&1 | findstr /C:"FALLO" /C:"EXCEP" /C:"pasados" >> "%OUT%"
)

echo.
echo ============ C) Entorno ============
>> "%OUT%" echo.
>> "%OUT%" echo ===== entorno =====
"%PY%" -c "import sys,platform;print('python',sys.version.split()[0],platform.platform())" >> "%OUT%" 2>&1
"%PY%" -c "import docx;print('python-docx OK')" >> "%OUT%" 2>&1
"%PY%" -c "import pdfplumber;print('pdfplumber OK')" >> "%OUT%" 2>&1
"%PY%" -c "import openpyxl;print('openpyxl OK')" >> "%OUT%" 2>&1
"%PY%" -c "import psycopg2;print('psycopg2 OK')" >> "%OUT%" 2>&1

echo.
echo ============================================================
echo   Listo. El detalle esta en:  %OUT%
echo   Dimelo por el chat y lo leo yo directamente.
echo ============================================================
echo.
pause
