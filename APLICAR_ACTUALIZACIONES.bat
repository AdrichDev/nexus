@echo off
chcp 65001 >nul
REM ============================================================
REM  nexus - aplica los *.new probando CUATRO vias, de menos a
REM  mas agresiva. Windows bloquea la escritura por motivos muy
REM  distintos (solo-lectura, permisos NTFS, archivo en uso o
REM  Controlled Folder Access) y cada uno tiene su remedio.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set /a OK=0
set /a KO=0
set "PENDIENTES="

REM --- ¿nexus esta arrancado? un archivo en uso no se puede pisar ---
tasklist /fi "imagename eq python.exe" 2>nul | find /i "python.exe" >nul
if not errorlevel 1 (
  echo   [!] Hay python.exe en marcha. Si nexus esta abierto, cierralo y
  echo       vuelve a ejecutar este .bat: un archivo en uso no se puede sustituir.
  echo.
)

for /r %%F in (*.new) do (
  set "SRC=%%F"
  set "DEST=%%~dpnF"
  echo   %%~nxF
  set "HECHO="

  REM 1) atributos (solo-lectura / oculto / sistema)
  attrib -r -h -s "!DEST!" >nul 2>&1
  copy /y "!SRC!" "!DEST!" >nul 2>&1
  if not errorlevel 1 set "HECHO=1"

  REM 2) permisos NTFS: tomar posesion y darse control total
  if not defined HECHO (
    takeown /f "!DEST!" >nul 2>&1
    icacls "!DEST!" /grant "%USERNAME%":F >nul 2>&1
    copy /y "!SRC!" "!DEST!" >nul 2>&1
    if not errorlevel 1 set "HECHO=1"
  )

  REM 3) apartar el original y poner el nuevo (crear SI suele dejarlo)
  if not defined HECHO (
    ren "!DEST!" "%%~nxF.viejo" >nul 2>&1
    if not errorlevel 1 (
      copy /y "!SRC!" "!DEST!" >nul 2>&1
      if not errorlevel 1 (
        set "HECHO=1"
        del /q "%%~dpF%%~nxF.viejo" >nul 2>&1
      ) else (
        ren "%%~dpF%%~nxF.viejo" "%%~nF" >nul 2>&1
      )
    )
  )

  if defined HECHO (
    del /q "!SRC!" >nul 2>&1
    echo       [OK] aplicado
    set /a OK+=1
  ) else (
    echo       [X] Windows lo sigue bloqueando
    set /a KO+=1
    set "PENDIENTES=!PENDIENTES! %%~nxF"
  )
)

echo.
if %OK% gtr 0 echo   Aplicadas %OK% actualizacion^(es^).
if %KO% gtr 0 (
  echo   Bloqueadas %KO%:!PENDIENTES!
  echo.
  echo   Que hacer, por orden:
  echo     1^) Cierra nexus ^(y cualquier editor con el archivo abierto^) y repite.
  echo     2^) Ejecuta este .bat como ADMINISTRADOR ^(clic derecho^).
  echo     3^) Seguridad de Windows ^> Proteccion contra ransomware ^>
  echo        Permitir una aplicacion ^> anade cmd.exe ^(o quita la proteccion
  echo        para la carpeta D:\Adrian\22. Proyectos\NEXUS^).
  echo.
  echo   Diagnostico del primero bloqueado:
  for %%P in (!PENDIENTES!) do (
    for /r %%Q in (%%P) do (
      attrib "%%~dpnQ"
      icacls "%%~dpnQ" 2>nul | findstr /i "denegado deny %USERNAME%"
      goto :fin
    )
  )
)
if %OK%==0 if %KO%==0 echo   No habia ninguna actualizacion pendiente. Todo al dia.
:fin
echo.
pause
