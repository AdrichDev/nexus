@echo off
REM ============================================================================
REM  nexus - compila e instala la app del movil (sin Android Studio)
REM
REM  POR QUE EXISTE ESTE ARCHIVO (31/07/2026):
REM  El apk se compilaba a mano en una maquina Debian y el binario del repo se
REM  quedo congelado el 24/07 mientras MainActivity.java seguia cambiando. El
REM  31/07 se instalo en el movil un apk de siete dias antes: le faltaba toda la
REM  vinculacion multi-direccion. Nadie podia notarlo, porque la app no dice que
REM  version lleva. De ahi este script: compilar tiene que ser un doble clic.
REM
REM  Firma con movil\nexus.keystore. La clave del keystore ORIGINAL se perdio y
REM  la app instalada (24/07) quedo firmada con el, asi que la firma cambia si o
REM  si: la PRIMERA instalacion desinstala la vieja una vez (se pierde la
REM  vinculacion, hay que releer el QR). Este script crea un keystore NUEVO solo
REM  con clave al azar guardada en movil\keystore.pass (gitignored): no tecleas
REM  ninguna contrasena, ni ahora ni nunca. A partir de esa vez, instala encima.
REM ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  === nexus: compilar la app del movil ===
echo.

REM ---- 1. herramientas ------------------------------------------------------
set "SDK=%LOCALAPPDATA%\Android\Sdk"
if not exist "%SDK%\build-tools" (
  echo  [X] No encuentro el SDK de Android en:
  echo      %SDK%
  echo      Instalalo desde Android Studio, o cambia la ruta aqui arriba.
  goto :fin
)

REM la build-tools mas nueva que haya instalada
set "BT="
for /f "delims=" %%d in ('dir /b /ad /on "%SDK%\build-tools"') do set "BT=%SDK%\build-tools\%%d"
if not exist "%BT%\aapt.exe" (
  echo  [X] Esa build-tools no trae aapt.exe: %BT%
  goto :fin
)

REM el android.jar contra el que compilar (vale cualquiera reciente)
set "JAR="
for /f "delims=" %%d in ('dir /b /ad /on "%SDK%\platforms"') do (
  if exist "%SDK%\platforms\%%d\android.jar" set "JAR=%SDK%\platforms\%%d\android.jar"
)
if not defined JAR (
  echo  [X] No hay ninguna platform con android.jar en %SDK%\platforms
  goto :fin
)

REM javac: JAVA_HOME manda; si no, el primero que aparezca en el PATH
set "JAVAC="
if defined JAVA_HOME if exist "%JAVA_HOME%\bin\javac.exe" set "JAVAC=%JAVA_HOME%\bin\javac.exe"
if not defined JAVAC (
  for /f "delims=" %%p in ('where javac 2^>nul') do if not defined JAVAC set "JAVAC=%%p"
)
if not defined JAVAC (
  echo  [X] No encuentro javac. Hace falta un JDK ^(17 o 21 valen^).
  goto :fin
)

echo  build-tools : %BT%
echo  android.jar : %JAR%
echo  javac       : %JAVAC%
echo.

REM ---- 2. compilar ----------------------------------------------------------
set "OBRA=%~dp0build"
if exist "%OBRA%" rd /s /q "%OBRA%"
mkdir "%OBRA%\src\com\nexus\app" 2>nul
mkdir "%OBRA%\gen" 2>nul
mkdir "%OBRA%\classes" 2>nul
copy /y "MainActivity.java" "%OBRA%\src\com\nexus\app\" >nul

echo  [1/5] recursos ^(aapt^)...
"%BT%\aapt.exe" package -f -m -M AndroidManifest.xml -S res -A assets -I "%JAR%" -J "%OBRA%\gen" -F "%OBRA%\base.apk"
if errorlevel 1 goto :roto

echo  [2/5] codigo ^(javac^)...
REM -source/-target 8: el bytecode de Android no admite versiones mas nuevas.
REM -encoding UTF-8: los comentarios del fuente llevan tildes.
"%JAVAC%" -encoding UTF-8 -source 8 -target 8 -nowarn -bootclasspath "%JAR%" ^
  -d "%OBRA%\classes" -sourcepath "%OBRA%\src;%OBRA%\gen" ^
  "%OBRA%\src\com\nexus\app\MainActivity.java" "%OBRA%\gen\com\nexus\app\R.java" 2>&1 | findstr /v /c:"bootstrap class path" /c:"source value 8" /c:"target value 8" /c:"deprecat"
if not exist "%OBRA%\classes\com\nexus\app\MainActivity.class" goto :roto

echo  [3/5] dex ^(d8^)...
REM Las clases van una a una en la linea de comandos, NO en un fichero de
REM argumentos (@lista): la ruta de este proyecto lleva espacios y un punto
REM ("22. Proyectos") y d8.bat se atraganta con el @ entrecomillado.
set "CLASES="
for /f "delims=" %%f in ('dir /b /s "%OBRA%\classes\*.class"') do set "CLASES=!CLASES! "%%f""
REM «call» obligatorio: d8.bat es un .bat, y sin call cmd salta a el y NO
REM vuelve nunca. El script padre moria aqui en silencio y con exito falso.
call "%BT%\d8.bat" --min-api 23 --lib "%JAR%" --output "%OBRA%"!CLASES!
if not exist "%OBRA%\classes.dex" goto :roto

echo  [4/5] empaquetar y alinear...
copy /y "%OBRA%\base.apk" "%OBRA%\sin-firmar.apk" >nul
pushd "%OBRA%"
"%BT%\aapt.exe" add sin-firmar.apk classes.dex >nul
popd
"%BT%\zipalign.exe" -f -p 4 "%OBRA%\sin-firmar.apk" "%OBRA%\alineado.apk"
if not exist "%OBRA%\alineado.apk" goto :roto

REM ---- 3. firmar ------------------------------------------------------------
echo  [5/5] firmar.
REM Android obliga a firmar TODO apk; sin firma no se instala. La clave del
REM keystore se guarda UNA vez con GUARDAR_CLAVE.bat en movil\keystore.pass
REM (gitignored, no sale de esta maquina) y aqui se lee de ahi: no se teclea nada.
set "PASSFILE=%~dp0keystore.pass"

REM keytool vive en el mismo bin que javac
for %%i in ("%JAVAC%") do set "JBIN=%%~dpi"
set "KEYTOOL=%JBIN%keytool.exe"

REM Caso raro: maquina limpia, sin keystore. Se crea uno con clave al azar. En
REM tu equipo NO pasa: ya tienes nexus.keystore con TU clave.
if not exist "nexus.keystore" (
  if not exist "%KEYTOOL%" (
    echo  [X] No encuentro keytool junto a javac: %KEYTOOL%
    goto :fin
  )
  set "KS_PASS=nx!RANDOM!!RANDOM!!RANDOM!k"
  > "%PASSFILE%" echo !KS_PASS!
  "%KEYTOOL%" -genkeypair -keystore "nexus.keystore" -alias nexus -keyalg RSA ^
    -keysize 2048 -validity 10000 -storepass "!KS_PASS!" -keypass "!KS_PASS!" ^
    -dname "CN=nexus" 2>nul
  if not exist "nexus.keystore" (
    echo  [X] No se pudo crear el keystore. Nada tocado.
    del "%PASSFILE%" 2>nul
    goto :fin
  )
  echo  Keystore nuevo creado. La clave queda en movil\keystore.pass.
)

REM Hay keystore pero no su clave: NO lo tocamos. Esa clave es la que mantiene
REM la firma y deja instalar encima sin desinstalar. Se guarda con el otro .bat.
if not exist "%PASSFILE%" (
  echo  [X] Falta la clave del keystore. Guardala una vez con:
  echo      movil\GUARDAR_CLAVE.bat
  echo      ^(la pide oculta, la comprueba y la deja en movil\keystore.pass^)
  goto :fin
)

REM set /p lee la linea TAL CUAL: no la interpreta cmd, asi que una clave con
REM ! ^ %% & sobrevive. No se copia a otra variable con %%..%%: eso SI la
REM corromperia (la expansion retardada se come los !). apksigner lee las dos
REM del entorno, la misma variable para el almacen y para la clave del alias.
set /p KS_PASS=<"%PASSFILE%"

REM el apk anterior se guarda: es el unico sitio del que salieron los iconos
if exist "nexus.apk" copy /y "nexus.apk" "nexus-anterior.apk" >nul

call "%BT%\apksigner.bat" sign --ks "nexus.keystore" --ks-key-alias nexus ^
  --ks-pass env:KS_PASS --key-pass env:KS_PASS --out "nexus.apk" "%OBRA%\alineado.apk"
set "FIRMA=%errorlevel%"
set "KS_PASS="
if not "%FIRMA%"=="0" (
  echo.
  echo  [X] La firma ha fallado. Si vienes de un keystore viejo, borra
  echo      movil\keystore.pass y movil\nexus.keystore y vuelve a lanzar esto:
  echo      se recrean solos. El apk anterior sigue intacto en nexus.apk
  goto :fin
)

echo.
echo  === APK firmado: movil\nexus.apk ===
call "%BT%\apksigner.bat" verify --print-certs "nexus.apk" | findstr /i "SHA-256"
echo.

REM ---- 4. instalar ----------------------------------------------------------
set "ADB=%SDK%\platform-tools\adb.exe"
if not exist "%ADB%" goto :fin
"%ADB%" devices | findstr /r /c:"device$" >nul
if errorlevel 1 (
  echo  Movil no conectado por USB. Cuando lo conectes:
  echo      movil\INSTALAR_EN_MOVIL_USB.bat
  goto :fin
)
echo  Movil detectado. Instalando encima de la version anterior...
"%ADB%" install -r "nexus.apk"
if errorlevel 1 (
  REM firma distinta a la instalada (keystore nuevo): la primera vez toca
  REM desinstalar la vieja. Perderas la vinculacion y hay que releer el QR.
  echo.
  echo  La firma no coincide con la app ya instalada. Desinstalo la vieja
  echo  y pongo la nueva (una sola vez; despues ya se instala encima sola)...
  "%ADB%" uninstall com.nexus.app >nul 2>&1
  "%ADB%" install "nexus.apk"
)
echo.
echo  Comprueba en el movil: Ajustes ^> Aplicaciones ^> nexus ^> version 2.7
echo  Si ves DOS iconos parecidos, el otro es la app vieja de WABIKS: desinstalala.

:fin
echo.
pause
exit /b

:roto
echo.
echo  [X] La compilacion ha fallado. Arriba esta el error.
echo      El apk anterior NO se ha tocado.
echo.
pause
exit /b 1
