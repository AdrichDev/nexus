@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "LOG=%~dp0install_log.txt"
echo === nexus: instalacion en el movil por USB === > "%LOG%"
echo Fecha: %DATE% %TIME% >> "%LOG%"

set "ADB="
where adb >nul 2>nul && set "ADB=adb"
if "%ADB%"=="" if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if "%ADB%"=="" if exist "%ProgramFiles%\platform-tools\adb.exe" set "ADB=%ProgramFiles%\platform-tools\adb.exe"
if "%ADB%"=="" if exist "%ProgramFiles(x86)%\platform-tools\adb.exe" set "ADB=%ProgramFiles(x86)%\platform-tools\adb.exe"
if "%ADB%"=="" if exist "%USERPROFILE%\platform-tools\adb.exe" set "ADB=%USERPROFILE%\platform-tools\adb.exe"
if "%ADB%"=="" if exist "%USERPROFILE%\Downloads\platform-tools\adb.exe" set "ADB=%USERPROFILE%\Downloads\platform-tools\adb.exe"
if "%ADB%"=="" if exist "%ProgramFiles%\BlueStacks_nxt\HD-Adb.exe" set "ADB=%ProgramFiles%\BlueStacks_nxt\HD-Adb.exe"
if "%ADB%"=="" if exist "%ProgramData%\BlueStacks_nxt\Engine\adb.exe" set "ADB=%ProgramData%\BlueStacks_nxt\Engine\adb.exe"

if "%ADB%"=="" (
  echo NO_ADB: no encuentro adb en el PC >> "%LOG%"
  echo NO_ADB >> "%LOG%"
  exit /b 1
)
echo ADB=%ADB% >> "%LOG%"

"%ADB%" start-server >> "%LOG%" 2>&1
echo --- adb devices --- >> "%LOG%"
"%ADB%" devices >> "%LOG%" 2>&1
echo --- adb install --- >> "%LOG%"
"%ADB%" install -r "%~dp0nexus.apk" >> "%LOG%" 2>&1
echo EXITCODE=%errorlevel% >> "%LOG%"
echo === FIN === >> "%LOG%"
exit /b 0
