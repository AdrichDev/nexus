@echo off
REM ============================================================
REM  nexus - INSTALADOR AUTOMATICO TOTAL v2
REM  0) CIERRA cualquier nexus en marcha (libera puerto y venv)
REM  1) Instala Python 3.12 si no existe
REM  2) Borra el .venv viejo (con reintento)
REM  3) Entorno nuevo + dependencias (nucleo y voz) con rutas explicitas
REM  4) Arranca nexus
REM  Log completo: install_nexus.log
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title nexus - Instalador automatico v2
set LOG=install_nexus.log
echo [%date% %time%] === INSTALADOR v2 INICIADO === > "%LOG%"

echo.
echo  ============================================
echo   nexus - INSTALADOR AUTOMATICO v2
echo  ============================================
echo.

REM ---------- PASO 0: cerrar nexus si esta corriendo ----------
echo [0/4] Cerrando instancias de nexus (si las hay)...
echo [0/4] Cerrando instancias previas >> "%LOG%"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*backend.desktop*' -or $_.CommandLine -like '*backend.app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >> "%LOG%" 2>&1
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8177 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >> "%LOG%" 2>&1
timeout /t 2 /nobreak >nul

REM ---------- PASO 1: Python 3.12 ----------
call :find_py312
if defined PYOK (
    echo [1/4] Python 3.12 encontrado.
    echo [1/4] Python 3.12 presente: launcher=%PYLAUNCH% exe=%PYEXE% >> "%LOG%"
    goto :venv
)
echo [1/4] Instalando Python 3.12 (2-3 min)...
echo [1/4] Instalando Python 3.12 >> "%LOG%"
where winget >nul 2>&1
if not errorlevel 1 (
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
)
call :find_py312
if defined PYOK goto :venv
echo [1/4] Descargando de python.org...
echo [1/4] Descarga directa python.org >> "%LOG%"
curl -L -o "%TEMP%\py312setup.exe" https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe >> "%LOG%" 2>&1
"%TEMP%\py312setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 >> "%LOG%" 2>&1
call :find_py312
if not defined PYOK (
    echo ERROR: no he podido instalar Python 3.12. Mira %LOG%
    echo ERROR instalando Python 3.12 >> "%LOG%"
    pause & exit /b 1
)

:venv
REM ---------- PASO 2: borrar venv viejo (con reintento) ----------
echo [2/4] Recreando el entorno virtual...
echo [2/4] Borrando .venv >> "%LOG%"
if exist ".venv" (
    rmdir /s /q ".venv" >> "%LOG%" 2>&1
    if exist ".venv" (
        echo [2/4] .venv bloqueado, reintento en 3 s... >> "%LOG%"
        timeout /t 3 /nobreak >nul
        rmdir /s /q ".venv" >> "%LOG%" 2>&1
    )
)
if exist ".venv" (
    echo ERROR: no puedo borrar .venv - cierra nexus y cualquier terminal
    echo         que este dentro de esa carpeta, y relanza este instalador.
    echo ERROR: .venv sigue bloqueado >> "%LOG%"
    pause & exit /b 1
)

REM crear venv (invocacion correcta segun launcher o exe)
if "%PYLAUNCH%"=="1" (
    py -3.12 -m venv .venv >> "%LOG%" 2>&1
) else (
    "%PYEXE%" -m venv .venv >> "%LOG%" 2>&1
)
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no se pudo crear el venv. Mira %LOG%
    echo ERROR creando venv >> "%LOG%"
    pause & exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; print('venv OK ->', sys.version)" >> "%LOG%" 2>&1

REM ---------- PASO 3: dependencias (rutas explicitas, sin activate) ----------
echo [3/4] Instalando dependencias del nucleo (3-5 min)...
echo [3/4] pip nucleo >> "%LOG%"
".venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR instalando el nucleo. Mira %LOG%
    echo ERROR pip nucleo >> "%LOG%"
    pause & exit /b 1
)
echo [3/4] Instalando la VOZ real (whisper)...
echo [3/4] pip voz >> "%LOG%"
".venv\Scripts\python.exe" -m pip install -r requirements-voice.txt >> "%LOG%" 2>&1
if errorlevel 1 (
    echo AVISO: voz no instalada - el resto funciona igual.
    echo AVISO: voz no instalada >> "%LOG%"
) else (
    echo [3/4] Voz real instalada correctamente.
    echo [3/4] Voz OK >> "%LOG%"
)

if not exist ".env" copy .env.example .env >nul
if not exist "config\settings.json" copy config\settings.example.json config\settings.json >nul

REM ---------- comprobacion: que lo instalado ARRANCA de verdad ----------
REM Una instalacion a medias (una carpeta que no se copio, un archivo a cero)
REM no se nota hasta que el usuario pide algo y le sale un error raro. Aqui se
REM comprueba en 2 segundos que las piezas cargan y que la config esta.
echo Comprobando la instalacion ...
".venv\Scripts\python.exe" -c "import sys, json, importlib; [importlib.import_module(m) for m in ('backend.app','backend.core.llm_runtime','backend.core.files_io')]; import importlib.util as u; [u.spec_from_file_location(n, 'skills/instagram/%%s.py' %% n).loader.exec_module(u.module_from_spec(u.spec_from_file_location(n, 'skills/instagram/%%s.py' %% n))) for n in ('analisis','descubrimiento','inteligencia','visual')]; json.load(open('config/umbrales.json', encoding='utf-8')); u.spec_from_file_location('nucleo', 'skills/nucleo/skill.py').loader.exec_module(u.module_from_spec(u.spec_from_file_location('nucleo', 'skills/nucleo/skill.py'))); print('OK')" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo AVISO: la comprobacion ha fallado. Mira el registro: %LOG%
    echo AVISO: comprobacion de instalacion FALLIDA >> "%LOG%"
) else (
    echo Comprobacion correcta: motor de analisis, umbrales y backend cargan.
    echo Comprobacion de instalacion OK >> "%LOG%"
)

REM ---------- PASO 4: arrancar ----------
echo [4/4] TODO LISTO. Arrancando nexus ...
echo [%date% %time%] === INSTALACION COMPLETADA OK === >> "%LOG%"
".venv\Scripts\python.exe" -m backend.desktop
exit /b 0

REM ---------- helper: localizar Python 3.12 ----------
:find_py312
set "PYOK=" & set "PYLAUNCH=0" & set "PYEXE="
py -3.12 -c "print(1)" >nul 2>&1 && (set "PYOK=1" & set "PYLAUNCH=1" & goto :eof)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYOK=1" & set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto :eof
)
if exist "C:\Program Files\Python312\python.exe" (
    set "PYOK=1" & set "PYEXE=C:\Program Files\Python312\python.exe" & goto :eof
)
if exist "C:\Python312\python.exe" (
    set "PYOK=1" & set "PYEXE=C:\Python312\python.exe" & goto :eof
)
goto :eof
