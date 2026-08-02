@echo off
REM ============================================================
REM  nexus - build del .exe unico (PyInstaller)
REM  Doble clic y listo. Resultado: dist\nexus.exe
REM
REM  OJO: dist\ sale LIMPIA a proposito (SIN tu settings.json, SIN
REM  secrets.json, SIN .env y SIN data\) para poder distribuirla:
REM  en el PC de destino nexus arranca DE CERO con su asistente.
REM  Tu configuracion personal sigue viviendo aqui, en el repo.
REM ============================================================
REM  Este .bat vive en installer\ pero trabaja desde la RAIZ del proyecto: ahi
REM  estan .venv, frontend, skills, knowledge y config, y ahi tiene que salir
REM  dist\. Por eso el cd es a "%~dp0.." y no a "%~dp0".
cd /d "%~dp0.."
call .venv\Scripts\activate.bat 2>nul
pip install pyinstaller >nul
pyinstaller installer\nexus.spec --noconfirm
if errorlevel 1 ( echo [nexus] ERROR en el build & pause & exit /b 1 )
REM -- recursos que viven JUNTO al exe (ACTUALIZABLES sin recompilar) --
if exist knowledge xcopy /e /i /y /q knowledge dist\knowledge >nul
if exist frontend xcopy /e /i /y /q frontend dist\frontend >nul
if exist skills xcopy /e /i /y /q skills dist\skills >nul
if not exist dist\config mkdir dist\config
copy /y config\settings.example.json dist\config\ >nul 2>nul
copy /y .env.example dist\.env.example >nul 2>nul
copy /y installer\nexus.ico dist\nexus.ico >nul 2>nul
REM -- por si quedaban de builds antiguos: fuera datos personales --
if exist dist\config\settings.json del /q dist\config\settings.json
if exist dist\config\secrets.json del /q dist\config\secrets.json
if exist dist\.env del /q dist\.env
if exist dist\data rmdir /s /q dist\data
echo.
echo [nexus] Build terminado: dist\nexus.exe  (LIMPIO, listo para distribuir)
echo          Siguiente paso: installer\build_installer.bat para crear nexus-Setup.exe
pause
