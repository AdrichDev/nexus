@echo off
REM  Escucha en segundo plano DOS PALMADAS para abrir nexus.
REM  (Ejecutalo asi, con doble clic, para VER en vivo lo que detecta.)
REM  Para dejarlo automatico al encender Windows: usa instalar_arranque_voz.bat
cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
python nexus_wake.py
