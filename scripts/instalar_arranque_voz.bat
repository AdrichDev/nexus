@echo off
setlocal
title nexus - Arranque por palmadas
REM  Este .bat vive en scripts\, pero el proyecto (.venv, data\) esta un nivel
REM  mas arriba. APPDIR se resuelve con %%~fI para que quede una ruta ABSOLUTA y
REM  limpia: acaba metida en el registro de Windows, y ahi un "...\scripts\.."
REM  a medio resolver es una bomba de relojeria.
cd /d "%~dp0.."

for %%I in ("%~dp0..") do set "APPDIR=%%~fI"
set "PYW=%APPDIR%\.venv\Scripts\pythonw.exe"
set "WAKE=%APPDIR%\scripts\nexus_wake.py"

echo.
echo   ================================================================
echo    nexus - abrir con DOS PALMADAS + arranque automatico de Windows
echo   ================================================================
echo.

if not exist "%PYW%" (
  echo   [X] No encuentro el entorno .venv:
  echo       %PYW%
  echo       Ejecuta primero run.bat una vez para crearlo, y vuelve aqui.
  echo.
  pause
  exit /b 1
)

REM --- Comprobar que estan sounddevice + numpy (es lo unico que necesitan las palmadas) ---
"%PYW%" -c "import sounddevice, numpy" 2>nul
if errorlevel 1 (
  echo   [!] AVISO: falta sounddevice/numpy en este entorno.
  echo       Se registrara igualmente, pero NO oira nada hasta instalarlos.
  echo       Solucion: abre run.bat una vez.
  echo.
)

REM --- Registrar en el arranque de Windows (usuario actual, SIN admin), oculto (pythonw) ---
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "NexusWake" /t REG_SZ /d "\"%PYW%\" \"%WAKE%\"" /f >nul
if errorlevel 1 (
  echo   [X] No pude registrar el arranque automatico.
  pause
  exit /b 1
)
echo   [OK] Registrado: al encender Windows, nexus escuchara las dos palmadas.

REM --- Arrancar el escuchador AHORA (oculto) para que funcione sin reiniciar ---
start "" "%PYW%" "%WAKE%"
echo   [OK] Escuchador arrancado ya, en segundo plano (sin ventana).
echo.
echo   Ahora da DOS PALMADAS seguidas  ->  y el programa se abre solo.
echo.
echo   Para quitarlo mas adelante: ejecuta  scripts\quitar_arranque_voz.bat
echo.
pause
endlocal
