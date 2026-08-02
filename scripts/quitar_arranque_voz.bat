@echo off
setlocal enabledelayedexpansion
title nexus - Quitar arranque por palmadas
REM  Vive en scripts\; el data\wake.pid que tiene que borrar esta en la RAIZ.
cd /d "%~dp0.."
echo.
echo   Quitando el arranque por palmadas y PARANDO el escuchador...

REM --- 1) Quitar del arranque de Windows ---
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "NexusWake" /f >nul 2>&1
if errorlevel 1 (
  echo   [i] No estaba registrado en el arranque (o ya se quito^).
) else (
  echo   [OK] Quitado del arranque de Windows.
)

REM --- 2) Parar el escuchador que este corriendo AHORA (por PID, lo mas fiable^) ---
set "STOPPED="
if exist "%~dp0..\data\wake.pid" (
  set /p WPID=<"%~dp0..\data\wake.pid"
  if defined WPID (
    taskkill /F /PID !WPID! >nul 2>&1
    if not errorlevel 1 set "STOPPED=1"
  )
  del "%~dp0..\data\wake.pid" >nul 2>&1
)

REM --- 3) Respaldo: matar cualquier python/pythonw que este ejecutando nexus_wake ---
REM     (PowerShell/CIM funciona en Windows 11, donde 'wmic' ya no viene incluido^)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | Where-Object { $_.CommandLine -like '*nexus_wake*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
if not errorlevel 1 set "STOPPED=1"

REM --- 4) Respaldo extra para Windows antiguos (por si aun tienen wmic^) ---
wmic process where "commandline like '%%nexus_wake%%'" call terminate >nul 2>&1

echo.
if defined STOPPED (
  echo   [OK] Escuchador de palmadas DETENIDO. Ya no se abrira solo con ruidos.
) else (
  echo   [i] No he encontrado ningun escuchador activo (puede que ya estuviera parado^).
)
echo       El resto de nexus sigue funcionando normal.
echo.
pause
endlocal
