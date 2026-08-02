@echo off
REM  Escucha en segundo plano DOS PALMADAS para abrir nexus.
REM  (Ejecutalo asi, con doble clic, para VER en vivo lo que detecta.)
REM  Para dejarlo automatico al encender Windows: usa scripts\instalar_arranque_voz.bat
REM  Vive en scripts\ pero corre desde la RAIZ: ahi estan .venv y data\.
cd /d "%~dp0.."
call .venv\Scripts\activate.bat 2>nul
.venv\Scripts\python.exe scripts\nexus_wake.py
