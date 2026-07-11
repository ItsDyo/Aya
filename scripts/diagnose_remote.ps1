$ErrorActionPreference = "Continue"

function Write-Check($Name, $State, $Detail = "") {
    $suffix = if ($Detail) { " - $Detail" } else { "" }
    Write-Host "[$State] $Name$suffix"
}

function Read-DotEnv($Path) {
    $values = @{}
    if (-not (Test-Path $Path)) {
        return $values
    }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $key, $value = $trimmed.Split("=", 2)
        $values[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $values
}

function Get-TailscaleCommand {
    $command = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $defaultPath = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $defaultPath) {
        return $defaultPath
    }
    return $null
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot
$envPath = Join-Path $projectRoot ".env"
$config = Read-DotEnv $envPath
$port = if ($config["AYA_PORT"]) { [int]$config["AYA_PORT"] } else { 7860 }
$hostName = if ($config["AYA_HOST"]) { $config["AYA_HOST"] } else { "127.0.0.1" }

Write-Host "Diagnostico remoto da Aya"
Write-Host ""

if (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Check "Python" "APROVADO" (& python --version)
}
else {
    Write-Check "Python" "REPROVADO" "python nao encontrado no PATH"
}

if (Test-Path ".venv") {
    Write-Check "Ambiente virtual" "APROVADO" ".venv encontrado"
}
else {
    Write-Check "Ambiente virtual" "AVISO" ".venv nao encontrado; usando Python global"
}

try {
    python -m pip check | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Check "Dependencias" "APROVADO" "pip check sem conflitos"
    }
    else {
        Write-Check "Dependencias" "REPROVADO" "pip check encontrou conflitos"
    }
}
catch {
    Write-Check "Dependencias" "REPROVADO" "nao foi possivel rodar pip check"
}

foreach ($module in @("gradio", "openai", "rich")) {
    python -c "import $module" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Check "Modulo Python $module" "APROVADO"
    }
    else {
        Write-Check "Modulo Python $module" "REPROVADO" "rode: python -m pip install -r requirements.txt"
    }
}

if (Test-Path $envPath) {
    Write-Check ".env" "APROVADO" ".env encontrado"
}
else {
    Write-Check ".env" "REPROVADO" "copie .env.example para .env"
}

if ($config["AYA_REMOTE_MODE"] -eq "true") {
    Write-Check "Modo remoto" "APROVADO"
}
else {
    Write-Check "Modo remoto" "REPROVADO" "AYA_REMOTE_MODE deve ser true"
}

if ($config["AYA_AUTH_ENABLED"] -eq "true") {
    Write-Check "Autenticacao" "APROVADO" "habilitada"
}
else {
    Write-Check "Autenticacao" "REPROVADO" "AYA_AUTH_ENABLED deve ser true"
}

if ($config["AYA_AUTH_USERNAME"]) {
    Write-Check "Usuario remoto" "APROVADO" "configurado"
}
else {
    Write-Check "Usuario remoto" "REPROVADO" "AYA_AUTH_USERNAME vazio"
}

if ($config["AYA_AUTH_PASSWORD"]) {
    Write-Check "Senha remota" "APROVADO" "configurada"
}
else {
    Write-Check "Senha remota" "REPROVADO" "AYA_AUTH_PASSWORD vazia"
}

if ($hostName -eq "127.0.0.1" -or $hostName -eq "localhost") {
    Write-Check "Host Gradio" "APROVADO" $hostName
}
else {
    Write-Check "Host Gradio" "AVISO" "prefira 127.0.0.1 com Tailscale Serve"
}

$tailscale = Get-TailscaleCommand
if ($tailscale) {
    Write-Check "Tailscale instalado" "APROVADO" $tailscale
    $status = & $tailscale status 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Check "Tailscale conectado" "APROVADO"
    }
    else {
        Write-Check "Tailscale conectado" "REPROVADO" "tailscale status falhou"
    }
    $tailscaleIp = (& $tailscale ip -4 2>$null | Select-Object -First 1)
    if ($tailscaleIp) {
        Write-Check "IP Tailscale" "APROVADO" $tailscaleIp
    }
    else {
        Write-Check "IP Tailscale" "AVISO" "nenhum IPv4 retornado"
    }
}
else {
    Write-Check "Tailscale instalado" "REPROVADO" "tailscale nao encontrado"
}

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 5 | Out-Null
    Write-Check "Ollama local" "APROVADO" "http://127.0.0.1:11434"
}
catch {
    Write-Check "Ollama local" "REPROVADO" "nao respondeu em 127.0.0.1:11434"
}

$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Check "Porta Gradio" "AVISO" "porta $port ja esta em uso"
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$port" -UseBasicParsing -TimeoutSec 5 | Out-Null
        Write-Check "Interface local" "APROVADO" "http://127.0.0.1:$port respondeu"
    }
    catch {
        Write-Check "Interface local" "AVISO" "porta ocupada, mas HTTP nao respondeu"
    }
}
else {
    Write-Check "Porta Gradio" "APROVADO" "porta $port livre"
    Write-Check "Interface local" "AVISO" "Aya ainda nao esta iniciada"
}

foreach ($path in @("app.py", "main.py", "aya\config.py", ".env.example")) {
    if (Test-Path $path) {
        Write-Check "Arquivo $path" "APROVADO"
    }
    else {
        Write-Check "Arquivo $path" "REPROVADO" "ausente"
    }
}

Write-Host ""
Write-Host "Comando recomendado para publicar na tailnet:"
if ($tailscale) {
    Write-Host "`"$tailscale`" serve $port"
}
else {
    Write-Host "tailscale serve $port"
}
Write-Host "Nao use tailscale funnel."
