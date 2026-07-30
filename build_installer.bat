@echo off
REM ============================================================
REM  nexus - genera el INSTALADOR (nexus-Setup.exe)
REM  Requisitos: 1) haber ejecutado build_exe.bat (crea dist\)
REM              2) NSIS instalado (https://nsis.sourceforge.io/Download)
REM ============================================================
cd /d "%~dp0"
if not exist dist\nexus.exe (
  echo [nexus] Falta dist\nexus.exe - ejecuta build_exe.bat primero.
  pause & exit /b 1
)
set NSIS=
if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set "NSIS=%ProgramFiles(x86)%\NSIS\makensis.exe"
if exist "%ProgramFiles%\NSIS\makensis.exe" set "NSIS=%ProgramFiles%\NSIS\makensis.exe"
where makensis >nul 2>nul && set "NSIS=makensis"
if "%NSIS%"=="" (
  echo [nexus] NSIS no esta instalado. Descargalo aqui:
  echo          https://nsis.sourceforge.io/Download
  start https://nsis.sourceforge.io/Download
  pause & exit /b 1
)
"%NSIS%" nexus_installer.nsi
if errorlevel 1 ( echo [nexus] ERROR generando el instalador & pause & exit /b 1 )
echo.
echo [nexus] Instalador creado: nexus-Setup.exe
echo          Ese archivo es el que le pasas a Ruben: doble clic e instalar.
pause
