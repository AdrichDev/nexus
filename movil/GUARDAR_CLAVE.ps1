# Guarda UNA VEZ la clave del keystore para firmar la app.
#
# Dos formas de dar la clave:
#   1) Escribirla en movil\clave.txt (con Notepad, la ves al teclear) y lanzar
#      esto: la lee de ahi, la comprueba y BORRA el clave.txt.
#   2) Sin clave.txt: la pide oculta por teclado.
#
# Comprueba la clave contra nexus.keystore ANTES de guardarla. Solo si abre el
# keystore la deja en movil\keystore.pass (gitignored). Nada de esto pasa por
# cmd, que se come los caracteres especiales de las contrasenas (! ^ % &).
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

if (-not (Test-Path 'nexus.keystore')) {
  Write-Host ' [X] No hay movil\nexus.keystore. Nada que firmar.'
  exit 1
}

# keytool: JAVA_HOME manda; si no, el del PATH
$keytool = $null
if ($env:JAVA_HOME -and (Test-Path "$env:JAVA_HOME\bin\keytool.exe")) {
  $keytool = "$env:JAVA_HOME\bin\keytool.exe"
}
if (-not $keytool) {
  $c = Get-Command keytool -ErrorAction SilentlyContinue
  if ($c) { $keytool = $c.Source }
}
if (-not $keytool) {
  Write-Host ' [X] No encuentro keytool. Hace falta un JDK (17 o 21 valen).'
  exit 1
}

# --- de donde sale la clave ---
$claveTxt = Join-Path $PSScriptRoot 'clave.txt'
$desdeFichero = Test-Path $claveTxt
if ($desdeFichero) {
  # Notepad suele dejar un salto de linea al final: se quita SOLO eso, no los
  # espacios (un espacio final podria ser parte de la clave, raro pero posible).
  $pass = [IO.File]::ReadAllText($claveTxt)
  $pass = $pass -replace "(`r`n|`n|`r)+$", ''
  Write-Host ' Clave leida de movil\clave.txt.'
} else {
  Write-Host ''
  $sec = Read-Host ' Clave del keystore (no se ve al teclearla)' -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  $pass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ([string]::IsNullOrEmpty($pass)) {
  Write-Host ' [X] Sin clave no se guarda nada.'
  exit 1
}

# Cuenta de caracteres: para que compruebes que se ha leido entero lo que pones.
Write-Host ''
Write-Host (" Caracteres leidos: {0}" -f $pass.Length)
$noAscii = ($pass.ToCharArray() | Where-Object { [int]$_ -gt 127 }).Count
if ($noAscii -gt 0) {
  Write-Host (" AVISO: {0} caracter(es) no-ASCII. Este keystore no admite eso" -f $noAscii)
  Write-Host '        (PKCS12 lo prohibe al crearlo): es una tecla equivocada.'
}

# Se escribe SIN BOM y SIN salto de linea final: el contenido exacto es la clave.
$passFile = Join-Path $PSScriptRoot 'keystore.pass'
[IO.File]::WriteAllText($passFile, $pass, (New-Object Text.UTF8Encoding($false)))

# Comprobar. -storepass:file = keytool lee la clave del fichero, no por argumento.
$out = & $keytool -list -keystore 'nexus.keystore' -storepass:file $passFile 2>&1
$ok = ($LASTEXITCODE -eq 0)

if (-not $ok) {
  Remove-Item $passFile -ErrorAction SilentlyContinue
  Write-Host ''
  Write-Host ' [X] Esa clave NO abre nexus.keystore. No he guardado nada.'
  Write-Host ''
  Write-Host ' Lo que dice keytool (esto NO es tu clave, es el error):'
  Write-Host ' ----------------------------------------------------------'
  $out | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" }
  Write-Host ' ----------------------------------------------------------'
  Write-Host ' "password was incorrect" = esa clave no es la del ALMACEN de'
  Write-Host ' este keystore. Otra cosa distinta = avisa, es otro problema.'
  if ($desdeFichero) {
    Write-Host ''
    Write-Host ' Tu movil\clave.txt sigue ahi por si fue un desliz al escribirlo.'
    Write-Host ' Corrigelo y vuelve a lanzar esto, o borralo cuando acabes.'
  }
  exit 1
}

# Correcta: si vino de clave.txt, se borra el plano.
if ($desdeFichero) { Remove-Item $claveTxt -ErrorAction SilentlyContinue }
Write-Host ''
Write-Host ' === Clave correcta y guardada en movil\keystore.pass ==='
Write-Host ' Ya puedes lanzar movil\COMPILAR_APK.bat: no pedira nada.'
exit 0
