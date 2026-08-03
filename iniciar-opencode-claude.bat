@echo off
chcp 65001 > nul
echo ========================================================
echo   Iniciando OpenCode con tu sesion de Claude Max + Headroom
echo ========================================================
echo.

set /p CLAUDE_SID="Pega tu sessionKey (sk-ant-sid01-...): "

if "%CLAUDE_SID%"=="" (
    echo.
    echo Error: No has introducido ningún sessionKey.
    pause
    exit /b 1
)

set ANTHROPIC_API_KEY=%CLAUDE_SID%
set CLAUDE_SESSION_KEY=%CLAUDE_SID%

echo.
echo Lanzando Headroom + OpenCode...
python -m headroom.cli wrap opencode
pause
