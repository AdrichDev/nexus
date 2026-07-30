@echo off
chcp 65001 >nul
set PYTHONUTF8=1
REM ============================================================
REM  nexus - COMPROBACION COMPLETA (specs v23)
REM  Doble clic aqui. Hace, por orden:
REM    1) aplica los *.new pendientes
REM    2) instala las dependencias que falten
REM    3) ejecuta la suite de contrato   -> TODO VERDE o no
REM    4) si tienes Playwright, las pruebas de interfaz reales
REM ============================================================
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo ============ 1/4  Aplicando actualizaciones pendientes ============
set /a N=0
for /r %%F in (*.new) do (
  echo   %%~nxF  ^-^>  %%~dpnF
  attrib -r -h -s "%%~dpnF" >nul 2>&1
  copy /y "%%F" "%%~dpnF" >nul 2>&1
  if errorlevel 1 (
    echo     [X] Windows no me deja escribir ahi ^(Proteccion contra ransomware^)
  ) else (
    del /q "%%F" >nul 2>&1
    set /a N+=1
  )
)
if %N%==0 echo   Nada pendiente.

echo.
echo ============ 2/4  Dependencias ============
"%PY%" -m pip install -q -r requirements.txt
if errorlevel 1 (echo   [X] Fallo instalando dependencias. Mira el error de arriba.) else (echo   Dependencias al dia.)

echo.
echo ============ 3/4  Suite de contrato ============
"%PY%" tests\run_all.py
set "RES=%errorlevel%"

echo.
echo ============ 4/4  Pruebas de interfaz (Playwright) ============
"%PY%" -c "import playwright" 2>nul
if errorlevel 1 (
  echo   [!] Playwright NO esta instalado: la interfaz queda SIN VERIFICAR.
  echo       Esto no es un "todo bien": es que no se ha comprobado.
  echo       Instalalo con un doble clic en INSTALAR_PRUEBAS_UI.bat
  set "UI=SIN VERIFICAR"
) else (
  "%PY%" tests\e2e\run_e2e.py
  if errorlevel 1 (set "UI=CON FALLOS") else (set "UI=OK")
)

echo.
echo ============================================================
if "%RES%"=="0" (echo   Suite de contrato: PASADA.) else (echo   Suite de contrato: HAY FALLOS. Copiame lo de arriba.)
echo   Interfaz ^(Playwright^): %UI%
echo ============================================================
echo.
pause
