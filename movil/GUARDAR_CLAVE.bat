@echo off
REM ============================================================================
REM  Guarda UNA VEZ la clave del keystore para firmar la app.
REM
REM  Todo el trabajo lo hace GUARDAR_CLAVE.ps1: cmd se come los caracteres
REM  especiales de las contrasenas (! ^ %% &), asi que la clave ni la lee ni la
REM  toca cmd. PowerShell la pide oculta, la comprueba contra nexus.keystore y
REM  la deja en movil\keystore.pass (gitignored). Despues COMPILAR_APK.bat la
REM  lee de ahi y no vuelve a preguntar nada.
REM ============================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0GUARDAR_CLAVE.ps1"
echo.
pause
exit /b
