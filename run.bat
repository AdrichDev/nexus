@echo off
REM ============================================================
REM  nexus — ARRANQUE DE UN CLIC
REM  Se auto-instala si hace falta. Prefiere Python 3.12/3.11
REM  (faster-whisper aun no soporta 3.13/3.14) y si la voz no se
REM  puede instalar, el resto del programa funciona igualmente.
REM ============================================================
cd /d "%~dp0"
title nexus - COMMAND CENTER

if not exist ".venv\Scripts\python.exe" (
    echo [nexus] Primera ejecucion: creando entorno...
    py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Necesitas Python instalado ^(ideal 3.12 de python.org^)
        pause & exit /b 1
    )
)
call .venv\Scripts\activate.bat
REM Activar NO basta. Si la carpeta del proyecto se renombra, el activate.bat del
REM venv sigue apuntando a la ruta VIEJA: PATH se rellena con un directorio que no
REM existe, «python» cae al del sistema y nexus arranca con otra version y otras
REM dependencias sin avisar. Por eso a partir de aqui se usa el ejecutable del
REM venv POR RUTA, que es inmune a eso.
set "PY=%~dp0.venv\Scripts\python.exe"

.venv\Scripts\python.exe -c "import fastapi, uvicorn, webview, googleapiclient" 2>nul
if errorlevel 1 (
    echo [nexus] Instalando dependencias principales...
    "%PY%" -m pip install --upgrade pip >nul
    "%PY%" -m pip install -r requirements.txt || (echo [nexus] ERROR instalando el nucleo & pause & exit /b 1)
)

REM Voz TTS (edge-tts neuronal GRATIS + pyttsx3 offline). Es lo que faltaba cuando
REM salia "TTS sin motor disponible". Se instala aparte y NO aborta el arranque.
.venv\Scripts\python.exe -c "import edge_tts, pyttsx3" 2>nul
if errorlevel 1 (
    echo [nexus] Instalando voz TTS ^(edge-tts + pyttsx3^)...
    "%PY%" -m pip install edge-tts pyttsx3 >nul 2>&1 && (
        echo [nexus] Voz TTS lista ✔
    ) || (
        echo [nexus] AVISO: no se pudo instalar la voz TTS ^(revisa tu conexion^).
    )
)

REM Documentos: pypdf (PDF) + python-docx (Word) para aprender apuntes y crear
REM archivos de Word en el escritorio. No aborta el arranque si falla.
.venv\Scripts\python.exe -c "import pypdf, docx" 2>nul
if errorlevel 1 (
    echo [nexus] Instalando soporte de documentos ^(pypdf + python-docx^)...
    "%PY%" -m pip install pypdf python-docx >nul 2>&1 && (
        echo [nexus] Documentos PDF/Word listos ✔
    ) || (
        echo [nexus] AVISO: no se pudo instalar pypdf/python-docx.
    )
)

REM Sensores de temperatura de CPU en Windows (wmi + pywin32). La GPU se lee con
REM nvidia-smi sin nada extra; la CPU necesita esto (y, para lectura completa,
REM tener abierto LibreHardwareMonitor). No aborta el arranque si falla.
.venv\Scripts\python.exe -c "import wmi" 2>nul
if errorlevel 1 (
    echo [nexus] Instalando sensores de temperatura ^(wmi^)...
    "%PY%" -m pip install wmi pywin32 >nul 2>&1 && (
        echo [nexus] Sensores de temperatura listos ✔
    ) || (
        echo [nexus] AVISO: no se pudo instalar wmi ^(la temperatura de CPU saldra n/d^).
    )
)

REM Engram: memoria de PROYECTO compartida entre nexus y Hermes. Es UN PAQUETE MAS
REM del instalador (como edge-tts o pypdf). Prefiere «go install» si tienes Go (sin
REM falsos positivos de antivirus); si no, baja el binario oficial del release y lo
REM VERIFICA por checksum antes de usarlo. No aborta el arranque si falla.
.venv\Scripts\python.exe -c "from backend.core import engram_bridge as e; from backend.core.config import settings as s; import sys; sys.exit(0 if e.installed({'settings': s}) else 1)" 2>nul
if errorlevel 1 (
    echo [nexus] Instalando Engram ^(memoria de proyecto compartida^)...
    .venv\Scripts\python.exe -m backend.core.engram_bridge && (
        echo [nexus] Engram listo ✔
    ) || (
        echo [nexus] AVISO: no se pudo instalar Engram. nexus funciona igual sin el.
    )
)

REM Voz real: se intenta APARTE; si falla (Python 3.13/3.14) no rompe nada
.venv\Scripts\python.exe -c "import faster_whisper, sounddevice" 2>nul
if errorlevel 1 (
    echo [nexus] Intentando instalar la voz real...
    "%PY%" -m pip install -r requirements-voice.txt && (
        echo [nexus] Voz real instalada ✔
    ) || (
        echo.
        echo [nexus] AVISO: voz real NO instalada. Tu Python es demasiado nuevo.
        echo          Solucion: instala Python 3.12 de python.org, borra la
        echo          carpeta .venv y vuelve a ejecutar run.bat
        echo          El resto del programa funciona igualmente.
        echo.
    )
)

REM ── AUTORREPARACIÓN del entorno ─────────────────────────────────────────
REM Python 3.13/3.14 rompe la VOZ (faster-whisper) y la VENTANA (pythonnet), y a
REM veces pydantic. Con Python 3.12 va TODO. Detectamos y, si hace falta, recreamos.
set "NEXUS_FIX="
REM 1) ¿El venv usa Python 3.13 o superior? → hay que recrear con 3.12
.venv\Scripts\python.exe -c "import sys;raise SystemExit(3 if sys.version_info[:2]>=(3,13) else 0)" 2>nul
if errorlevel 3 (
    echo [nexus] El entorno usa Python 3.13+ ^(rompe la voz y la ventana de escritorio^).
    set "NEXUS_FIX=1"
)
REM 2) ¿El nucleo importa? Si no, reinstala pydantic; si sigue roto, recrear.
.venv\Scripts\python.exe -c "import fastapi" 2>nul
if errorlevel 1 (
    echo [nexus] El nucleo no arranca; reparando pydantic_core...
    "%PY%" -m pip install --force-reinstall --no-cache-dir pydantic pydantic-core >nul 2>&1
    .venv\Scripts\python.exe -c "import fastapi" 2>nul
    if errorlevel 1 set "NEXUS_FIX=1"
)
if defined NEXUS_FIX call :recreate_venv

REM ── VENTANA DE ESCRITORIO (pythonnet/cffi) ───────────────────────────────
REM Sin el binario _cffi_backend, pywebview no crea la ventana y cae al navegador.
REM A veces no queda instalado (o lo borra el antivirus). Lo comprobamos y reponemos.
.venv\Scripts\python.exe -c "import clr" 2>nul
if errorlevel 1 (
    echo [nexus] Reparando la ventana de escritorio ^(cffi/pythonnet^)...
    "%PY%" -m pip install --force-reinstall --no-cache-dir cffi pycparser >nul 2>&1
    "%PY%" -m pip install --force-reinstall --no-cache-dir pywin32 clr-loader pythonnet >nul 2>&1
    .venv\Scripts\python.exe -c "import clr" 2>nul
    if errorlevel 1 (
        echo [nexus] AVISO: la ventana nativa sigue sin cargar. Si usas antivirus, puede
        echo          estar borrando _cffi_backend.pyd: excluye la carpeta .venv y repite.
        echo          Mientras tanto, nexus abrira en el navegador ^(funciona igual^).
    ) else (
        echo [nexus] Ventana de escritorio reparada ✔
    )
)

if not exist ".env" copy .env.example .env >nul
if not exist "config\settings.json" copy config\settings.example.json config\settings.json >nul

REM ── LIBERAR EL PUERTO 8177 ────────────────────────────────────────────────
REM Si un nexus anterior quedo colgado, mantiene el puerto ocupado y el nuevo
REM revienta con «[Errno 10048] ... solo se permite un uso de cada direccion de
REM socket», arrancando con el CODIGO VIEJO. Matamos SOLO el proceso que ESCUCHA
REM en 8177 (el servidor), no las conexiones del navegador (ESTABLISHED).
echo [nexus] Liberando el puerto 8177 (por si quedo una instancia anterior)...
set "WBK_KILLED="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8177 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1 && set "WBK_KILLED=1"
)
if defined WBK_KILLED (
    echo [nexus] Instancia anterior cerrada. Espero a que suelte el puerto...
    ping -n 3 127.0.0.1 >nul
)

echo [nexus] Iniciando...
"%PY%" -m backend.desktop
if errorlevel 1 pause
exit /b 0

REM ── Subrutina: recrear el entorno LIMPIO con Python 3.12 ──────────────────
:recreate_venv
echo [nexus] Recreo el entorno LIMPIO con Python 3.12 ^(voz + ventana + nucleo^)...
rmdir /s /q .venv
py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul
if not exist ".venv\Scripts\python.exe" (
    echo [nexus] No encuentro Python 3.12 — lo instalo con winget ^(tarda un par de minutos^)...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
    py -3.12 -m venv .venv 2>nul
)
if not exist ".venv\Scripts\python.exe" (
    echo [nexus] No pude preparar Python 3.12 automaticamente. Instalalo de python.org
    echo          ^(marca «Add to PATH»^) y vuelve a ejecutar run.bat.
    pause & exit /b 1
)
call .venv\Scripts\activate.bat
set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -r requirements.txt || (echo [nexus] ERROR instalando el nucleo & pause & exit /b 1)
"%PY%" -m pip install edge-tts pyttsx3 pypdf python-docx wmi pywin32 >nul 2>&1
"%PY%" -m pip install -r requirements-voice.txt >nul 2>&1
echo [nexus] Entorno recreado con Python 3.12 ^(limpio^). Voz y ventana listas.
goto :eof
