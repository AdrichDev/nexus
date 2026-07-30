# -*- mode: python ; coding: utf-8 -*-
"""
nexus — spec de PyInstaller.
Empaqueta backend + frontend + skills en un único nexus.exe.
Build:  build_exe.bat   (o: pyinstaller nexus.spec)
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    ['backend/desktop.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('skills', 'skills'),
        ('config/settings.example.json', 'config'),
        ('config/n8n_flujo_ejemplo.json', 'config'),
        ('.env.example', '.'),
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
    icon=str(ROOT / 'nexus.ico') if (ROOT / 'nexus.ico').exists() else None,
)
