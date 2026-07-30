@echo off
REM ============================================================
REM  nexus - LIMPIAR Y ORDENAR   (herramienta de un solo uso)
REM  Generado por Claude. Puedes revisarlo entero antes de correrlo.
REM
REM  QUE HACE:
REM   1) Mueve los SPECS (SPECS.md, SPECS_v19..v22) a  docs\
REM   2) Borra los backups de codigo   *.bak_*   (en backend\ skills\ tests\ frontend\)
REM   3) Borra los ficheros vacios      *.wnew
REM   4) Borra las caches              __pycache__  (se regeneran solas al arrancar)
REM
REM  QUE **NO** TOCA (a proposito):
REM   - config\settings.json.bak  y  config\secrets.json.bak  (backups de TU config)
REM   - data\   .venv\   .git\   dist\   build\   config\   (nada de eso)
REM   - requirements*.txt / .lock  (se quedan en la raiz, como pediste)
REM
REM  Todo relativo a la carpeta de este .bat, asi que solo actua sobre el repo.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo ============================================================
echo  nexus - limpiar y ordenar
echo  Carpeta: %CD%
echo ============================================================
echo.

REM ---------- 1) SPECS -> docs\ ----------
echo [1/4] Moviendo los SPECS a docs\ ...
if not exist "docs" mkdir "docs"
set /a NSPEC=0
for %%f in ("SPECS.md" "SPECS_v19.md" "SPECS_v20.md" "SPECS_v21.md" "SPECS_v22.md") do (
    if exist "%%~f" (
        move /y "%%~f" "docs\" >nul && ( echo    movido  %%~f  -^>  docs\ & set /a NSPEC+=1 )
    )
)
echo    %NSPEC% SPECS movidos a docs\
echo.

REM ---------- 2) backups de codigo *.bak_* ----------
echo [2/4] Borrando backups de codigo *.bak_* ...
set /a NBAK=0
for /f "delims=" %%f in ('dir /b /s /a-d "backend\*" "skills\*" "tests\*" "frontend\*" 2^>nul ^| findstr /i "\.bak_"') do (
    del /q "%%f" 2>nul && set /a NBAK+=1
)
echo    !NBAK! backups .bak_* borrados
echo.

REM ---------- 3) ficheros vacios *.wnew ----------
echo [3/4] Borrando ficheros *.wnew ...
set /a NWNEW=0
for /f "delims=" %%f in ('dir /b /s /a-d "backend\*" "skills\*" "tests\*" "frontend\*" 2^>nul ^| findstr /i "\.wnew$"') do (
    del /q "%%f" 2>nul && set /a NWNEW+=1
)
echo    !NWNEW! ficheros .wnew borrados
echo.

REM ---------- 4) __pycache__ ----------
echo [4/4] Borrando cache __pycache__ ...
set /a NPYC=0
for /f "delims=" %%d in ('dir /b /s /ad "backend\*" "skills\*" "tests\*" 2^>nul ^| findstr /i "__pycache__$"') do (
    rmdir /s /q "%%d" 2>nul && set /a NPYC+=1
)
echo    !NPYC! carpetas __pycache__ borradas
echo.

echo ============================================================
echo  LISTO.  SPECS -^> docs\   ^|   basura borrada.
echo  (Consejo: si usas git, revisa los cambios con  git status  antes de commitear.)
echo ============================================================
pause
