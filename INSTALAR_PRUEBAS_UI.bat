@echo off
chcp 65001 >nul
set PYTHONUTF8=1
REM ============================================================
REM  nexus - instala Playwright + Chromium para las pruebas de
REM  INTERFAZ (tests\e2e\run_e2e.py). Solo hace falta UNA vez.
REM  Descarga ~130 MB: tarda un par de minutos.
REM ============================================================
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo ============ 1/3  Instalando Playwright ============
"%PY%" -m pip install playwright
if errorlevel 1 goto :error

echo.
echo ============ 2/3  Descargando Chromium (~130 MB) ============
"%PY%" -m playwright install chromium
if errorlevel 1 goto :error

echo.
echo ============ 3/3  Ejecutando las pruebas de interfaz ============
"%PY%" tests\e2e\run_e2e.py
set "RES=%errorlevel%"
echo.
echo ============================================================
if "%RES%"=="0" (
  echo   TODO VERDE. Informe y capturas en:  data\e2e\
) else (
  echo   HAY FALLOS. Mira data\e2e\report.md y copiamelo por el chat.
)
echo ============================================================
echo.
pause
exit /b %RES%

:error
echo.
echo   [X] Fallo la instalacion. Copiame el error de arriba.
echo.
pause
exit /b 1
