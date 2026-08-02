@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem  Repositorio de Adri, ya puesto para poder lanzar esto con DOBLE CLIC.
rem  Si algun dia cambias de repo, pasale la URL nueva como argumento:
rem     SUBIR_A_GITHUB.bat https://github.com/OTRO/otro.git
set ORIGEN_DEFECTO=https://github.com/AdrichDev/nexus.git

echo ============================================================
echo   nexus - PRIMER COMMIT Y SUBIDA A GITHUB
echo ============================================================
echo.
echo   Destino: !ORIGEN_DEFECTO!
echo   Repositorio PRIVADO. Antes de subir nada se revisa que no
echo   se cuele ninguna clave: si algo huele a secreto, esto para.
echo.

rem ---------- 1) Herramientas ----------
where git >nul 2>&1
if errorlevel 1 (
  echo [X] No tienes git instalado o no esta en el PATH.
  echo     Descargalo en https://git-scm.com/download/win y vuelve a lanzar esto.
  goto :fin
)
rem  El python del PROYECTO, nunca el del PATH. El del sistema es 3.14 y este
rem  proyecto necesita 3.12: con el equivocado la revision puede ni arrancar, y
rem  encima deja cache __pycache__ compilada por un interprete no soportado.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "!PY!" (
  echo [X] No encuentro el entorno del proyecto ^(.venv^), y la revision de
  echo     seguridad se hace con el, no con el python del sistema.
  echo     Lanza run.bat una vez: el mismo repara el .venv.
  goto :fin
)

rem ---------- 2) Identidad de git ----------
for /f "delims=" %%n in ('git config --get user.name 2^>nul') do set GNAME=%%n
for /f "delims=" %%m in ('git config --get user.email 2^>nul') do set GMAIL=%%m
if "!GNAME!"=="" (
  echo Git no sabe quien eres todavia.
  set /p GNAME="  Tu nombre para los commits: "
  git config --global user.name "!GNAME!"
)
if "!GMAIL!"=="" (
  set /p GMAIL="  Tu email de GitHub: "
  git config --global user.email "!GMAIL!"
)
echo  Commits como: !GNAME! ^<!GMAIL!^>
echo.

rem ---------- 3) Repositorio local ----------
if not exist ".git" (
  echo ============ Creando el repositorio local ============
  git init -b main >nul 2>&1
  if errorlevel 1 (
    git init >nul
    git branch -M main >nul 2>&1
  )
  echo  [OK] repositorio creado, rama "main"
) else (
  echo  [OK] ya habia repositorio local
)
git config core.autocrlf false >nul 2>&1

rem ---------- 3a) ACTUALIZACIONES PENDIENTES (.new) ----------
rem  Cuando Windows tiene un archivo en solo-lectura, la version nueva se deja
rem  al lado como "X.new" y hay que moverla encima. Si eso se queda a medias,
rem  subirias codigo viejo (y la revision te para por una clave que YA estaba
rem  corregida en el .new). Asi que se comprueba aqui, antes de nada.
rem  Solo se miran las carpetas del proyecto: nunca .venv ni data. Y los comodines
rem  van SIN comillas a proposito: entre comillas, "for" no expande el * y trataria
rem  el patron como un nombre literal.
set LISTA=*.new backend\*.new backend\core\*.new frontend\*.new frontend\js\*.new frontend\css\*.new tests\*.new tests\e2e\*.new config\*.new movil\*.new
set PENDIENTES=0
for %%f in (%LISTA%) do set PENDIENTES=1
for /d %%s in (skills\*) do (
  for %%f in (%%s\*.new) do set PENDIENTES=1
)
if !PENDIENTES!==1 (
  echo.
  echo ============ Actualizaciones pendientes ============
  echo  Hay archivos nuevos sin aplicar ^(quedaron como .new porque Windows
  echo  tenia el original en solo-lectura^). Mira la FECHA: si alguno es viejo,
  echo  di N y revisalo antes, porque aplicarlo pisaria una version mas nueva.
  echo.
  for %%f in (%LISTA%) do echo    %%~tf   %%f
  for /d %%s in (skills\*) do (
    for %%f in (%%s\*.new) do echo    %%~tf   %%f
  )
  echo.
  set /p AP="Los aplico ahora? (S/N): "
  if /i "!AP!"=="S" (
    for %%f in (%LISTA%) do call :aplicar "%%f"
    for /d %%s in (skills\*) do (
      for %%f in (%%s\*.new) do call :aplicar "%%f"
    )
  ) else (
    echo  [!] Los dejo. Ojo: si alguno traia una correccion de seguridad, la
    echo      revision de mas abajo te va a parar por eso mismo.
  )
)

rem ---------- 3b) Workflow de CI ajustado a repo PRIVADO ----------
rem  La carpeta .github\workflows esta protegida contra escritura remota (ahi
rem  vive codigo que GitHub ejecuta), asi que el archivo nuevo esta en la raiz
rem  y lo colocas TU con este paso.
if exist "security-ci-nuevo.yml" (
  echo.
  echo ============ Workflow de seguridad ============
  echo  Version del workflow ajustada a repo PRIVADO: desactiva el paso que sube
  echo  el SARIF a la pestana Security ^(en privado necesita GitHub Advanced
  echo  Security y pondria el CI en rojo en cada ejecucion^). El escaneo de Trivy
  echo  y pip-audit sigue igual, y el CI sigue fallando ante HIGH/CRITICAL.
  echo.
  set /p WF="Lo copio sobre .github\workflows\security-ci.yml? (S/N): "
  if /i "!WF!"=="S" (
    if not exist ".github\workflows" mkdir ".github\workflows"
    attrib -r ".github\workflows\security-ci.yml" >nul 2>&1
    copy /y "security-ci-nuevo.yml" ".github\workflows\security-ci.yml" >nul
    if errorlevel 1 (
      echo  [X] No he podido copiarlo. Hazlo a mano y borra security-ci-nuevo.yml.
    ) else (
      del "security-ci-nuevo.yml" >nul 2>&1
      echo  [OK] workflow actualizado.
    )
  ) else (
    echo  Lo dejo como esta ^(el archivo sigue en la raiz: security-ci-nuevo.yml^).
  )
)

rem ---------- 4) Preparar todo, respetando el .gitignore ----------
rem  El "rm --cached" es IMPRESCINDIBLE: un archivo que ya estuviera rastreado se
rem  sube aunque lo pongas en el .gitignore. Vaciando el indice y volviendo a
rem  anadir, las reglas nuevas se aplican de verdad.
echo.
echo ============ Preparando los archivos ============
git rm -r --cached . >nul 2>&1
git add -A
if errorlevel 1 (
  echo [X] git add ha fallado.
  goto :fin
)

rem ---------- 5) LA REVISION ----------
echo.
echo ============ Revision de seguridad ============
rem  Primero el detector se prueba A SI MISMO, en silencio: un "LIMPIO" de un
rem  detector roto es peor que no revisar nada. Solo se ve si algo falla.
"!PY!" scripts\revisar_antes_de_subir.py --autotest >nul 2>&1
if errorlevel 1 (
  echo [X] El PROPIO detector no pasa su autocomprobacion. No me fio de su
  echo     veredicto, asi que no subo nada. Detalle:
  echo.
  "!PY!" scripts\revisar_antes_de_subir.py --autotest
  call :deshacer
  goto :fin
)
echo  [OK] el detector pasa su autocomprobacion ^(15 casos^)
echo.
"!PY!" scripts\revisar_antes_de_subir.py
if errorlevel 1 (
  echo.
  echo ============================================================
  echo   NO SE HA SUBIDO NADA, ni se ha hecho commit.
  echo   Arregla lo de arriba y vuelve a lanzar esto.
  echo ============================================================
  call :deshacer
  goto :fin
)

rem ---------- 6) Confirmacion ----------
echo.
set /p OK="Hago el commit con estos archivos? (S/N): "
if /i not "!OK!"=="S" (
  echo  Cancelado. No se ha hecho commit.
  call :deshacer
  goto :fin
)

git diff --cached --quiet
if not errorlevel 1 (
  echo  No hay cambios que guardar: ya estaba todo commiteado.
  goto :remoto
)
git rev-parse --verify HEAD >nul 2>&1
if errorlevel 1 (
  set MSG=nexus: primer commit ^(runtime de modelos v25, tablero, memoria y skills^)
) else (
  set MSG=nexus: actualizacion
)
git commit -q -m "!MSG!"
if errorlevel 1 (
  echo [X] El commit ha fallado. Mira el mensaje de arriba.
  goto :fin
)
echo  [OK] commit hecho.

:remoto
rem ---------- 7) Subida ----------
echo.
echo ============ Subida a GitHub ============
set ORIGEN=
for /f "delims=" %%r in ('git remote get-url origin 2^>nul') do set ORIGEN=%%r
if not "%~1"=="" (
  if "!ORIGEN!"=="" (
    git remote add origin "%~1"
  ) else (
    git remote set-url origin "%~1"
  )
  set ORIGEN=%~1
)
if "!ORIGEN!"=="" (
  if not "!ORIGEN_DEFECTO!"=="" (
    git remote add origin "!ORIGEN_DEFECTO!" >nul 2>&1
    set ORIGEN=!ORIGEN_DEFECTO!
  )
)
if "!ORIGEN!"=="" (
  echo  No hay repositorio remoto configurado. Lanzalo asi:
  echo      SUBIR_A_GITHUB.bat https://github.com/TU_USUARIO/nexus.git
  echo  El commit ya esta hecho en local: no se pierde nada.
  goto :fin
)

echo  Remoto: !ORIGEN!
set /p OK2="Subo la rama main a ese repositorio? (S/N): "
if /i not "!OK2!"=="S" (
  echo  Cancelado. El commit local sigue ahi; puedes subirlo cuando quieras con:
  echo      git push -u origin main
  goto :fin
)
git push -u origin main
if errorlevel 1 (
  echo.
  echo [X] El push ha fallado. Lo mas habitual:
  echo     - Falta autenticarse: lo facil es GitHub CLI ^("gh auth login"^), o un
  echo       token personal de GitHub usado como contrasena.
  echo     - El repositorio remoto no existe todavia, o la URL esta mal escrita.
  echo     - El remoto ya tiene commits: prueba "git pull --rebase origin main".
  echo.
  echo     El commit local NO se ha perdido. Arregla y repite: git push -u origin main
  goto :fin
)
echo.
echo ============================================================
echo   LISTO. Ya esta en GitHub ^(privado^).
echo   Recuerda: config\ y .env NO se han subido. Una copia nueva
echo   del repo NO arranca sin volver a poner tus claves.
echo ============================================================
goto :fin

rem ---------- Aplicar un .new encima de su original ----------
rem  %~dpn1 quita la extension ".new", asi que "algo.py.new" -> "algo.py".
:aplicar
attrib -r "%~dpn1" >nul 2>&1
move /y "%~1" "%~dpn1" >nul
if errorlevel 1 (
  echo    [X] no he podido aplicar %~nx1 ^(cierra nexus y reintenta^)
) else (
  echo    [OK] %~nx1
)
exit /b 0

rem ---------- Deshacer lo preparado, dejando el repo como estaba ----------
:deshacer
git rev-parse --verify HEAD >nul 2>&1
if errorlevel 1 (
  git rm -r --cached . >nul 2>&1
) else (
  git reset -q >nul 2>&1
)
exit /b 0

:fin
echo.
pause
endlocal
