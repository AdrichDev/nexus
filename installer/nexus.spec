# -*- mode: python ; coding: utf-8 -*-
"""
nexus — spec de PyInstaller.
Empaqueta backend + frontend + skills en un único nexus.exe.
Build:  installer\build_exe.bat   (o: pyinstaller installer\nexus.spec)
"""

import sys
from pathlib import Path

# Este .spec vive en installer/, pero TODO lo que empaqueta (backend, frontend,
# skills, config) cuelga de la raíz del repositorio. Por eso las rutas se
# construyen ABSOLUTAS desde ROOT: si fueran relativas dependerían del directorio
# desde el que se lance pyinstaller y el .exe saldría sin frontend ni skills.
AQUI = Path(SPECPATH)          # ...\nexus\installer  (aquí están el .ico y los .bmp)
ROOT = AQUI.parent             # ...\nexus            (la raíz del proyecto)

a = Analysis(
    [str(ROOT / 'backend' / 'desktop.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'frontend'), 'frontend'),
        (str(ROOT / 'skills'), 'skills'),
        (str(ROOT / 'config' / 'settings.example.json'), 'config'),
        (str(ROOT / 'config' / 'n8n_flujo_ejemplo.json'), 'config'),
        (str(ROOT / '.env.example'), '.'),
    ],
    hiddenimports=[
        'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
        'pyttsx3.drivers', 'pyttsx3.drivers.sapi5',
        'psycopg2', 'sympy', 'keyboard', 'mss', 'send2trash',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'test'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='nexus',
    debug=False,
    strip=False,
    upx=False,
    console=False,            # sin consola: solo la ventana HUD
    icon=str(AQUI / 'nexus.ico') if (AQUI / 'nexus.ico').exists() else None,
)
