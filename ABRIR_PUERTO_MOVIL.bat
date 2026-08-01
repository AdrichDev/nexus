@echo off
rem ============================================================================
rem  ABRIR_PUERTO_MOVIL.bat - deja que el movil llegue a nexus por la WiFi.
rem
rem  POR QUE EXISTE (31/07/2026). El QR ofrecia PC_ADRI.local:8177 y el movil se
rem  comia un "conexion rechazada". Dos causas encadenadas:
rem    1. uvicorn estaba atado solo a 127.0.0.1  -> arreglado en backend/desktop.py
rem    2. el cortafuegos de Windows bloquea la entrada -> lo arregla ESTE archivo
rem
rem  COMO SE USA: clic derecho -> "Ejecutar como administrador".
rem  Sin admin no funciona, y te lo dice en vez de fallar en silencio.
rem
rem  DESHACER (tambien como administrador):
rem    netsh advfirewall firewall delete rule name="nexus 8177 (LAN de casa)"
rem ============================================================================
setlocal
title nexus - abrir el 8177 para el movil

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [X] Esto necesita permisos de administrador.
  echo      Cierra esta ventana, clic derecho sobre ABRIR_PUERTO_MOVIL.bat
  echo      y elige "Ejecutar como administrador".
  echo.
  pause
  exit /b 1
)

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo  [X] No encuentro %PY%
  echo      Lanza run.bat una vez: el mismo repara el entorno.
  pause
  exit /b 1
)

echo.
echo  === 1) Tu red pasa de Publica a Privada ===
rem  Con perfil Publico, Windows bloquea TODA entrada y la regla de abajo ni se
rem  llega a aplicar. Privada es lo correcto para la red de tu casa. En la WiFi
rem  de un bar seguiras en Publico y nexus quedara cerrado: eso es lo que
rem  queremos, no un descuido.
powershell -NoProfile -Command "Get-NetConnectionProfile | Where-Object {$_.NetworkCategory -eq 'Public'} | Set-NetConnectionProfile -NetworkCategory Private"

echo.
echo  === 2) Regla de entrada para el 8177 ===
rem  Lo mas ceniido que permite netsh: un solo puerto, un solo programa, un solo
rem  perfil y solo desde tu propia subred. Nada de "any" en ningun campo.
netsh advfirewall firewall delete rule name="nexus 8177 (LAN de casa)" >nul 2>&1
netsh advfirewall firewall add rule ^
  name="nexus 8177 (LAN de casa)" ^
  dir=in action=allow protocol=TCP localport=8177 ^
  program="%PY%" ^
  profile=private remoteip=localsubnet ^
  description="Permite que el movil llegue a nexus dentro de la red de casa."

echo.
echo  === 3) Como ha quedado ===
powershell -NoProfile -Command "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory | Format-Table -AutoSize"
netsh advfirewall firewall show rule name="nexus 8177 (LAN de casa)"

echo.
echo  Listo. Arranca nexus con run.bat y vuelve a escanear el QR.
echo.
pause
endlocal
