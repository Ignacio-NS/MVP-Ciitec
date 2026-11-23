# Genera un certificado self-signed para Nginx (TLS 1.3, RNF-002) en Windows.
# Requiere OpenSSL (viene con Git for Windows): C:\Program Files\Git\usr\bin\openssl.exe
$dir = Join-Path $PSScriptRoot "..\infra\nginx\certs"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$openssl = (Get-Command openssl -ErrorAction SilentlyContinue).Source
if (-not $openssl) {
    $gitOpenssl = "C:\Program Files\Git\usr\bin\openssl.exe"
    if (Test-Path $gitOpenssl) {
        $openssl = $gitOpenssl
    } else {
        Write-Error "No se encontro OpenSSL. Instalalo o agrega Git for Windows al PATH."
        exit 1
    }
}
& $openssl req -x509 -nodes -newkey rsa:2048 -days 825 `
  -keyout (Join-Path $dir "server.key") `
  -out (Join-Path $dir "server.crt") `
  -subj "/C=CL/O=Ejercito de Chile/CN=localhost"

Write-Host "Certificados generados en $dir"
