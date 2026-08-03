# Script de inicio para OpenCode con Claude Max (SessionKey) y Headroom en PowerShell
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Iniciando OpenCode con tu sesión de Claude Max + Headroom" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$SessionKey = Read-Host "Pega tu sessionKey de Claude (sk-ant-sid01-...)"

if ([string]::IsNullOrWhiteSpace($SessionKey)) {
    Write-Host "Error: No introdujiste ningún sessionKey." -ForegroundColor Red
    exit 1
}

$env:ANTHROPIC_API_KEY = $SessionKey
$env:CLAUDE_SESSION_KEY = $SessionKey

Write-Host "`nLanzando Headroom + OpenCode..." -ForegroundColor Green
python -m headroom.cli wrap opencode
