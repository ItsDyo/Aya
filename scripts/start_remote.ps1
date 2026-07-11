$ErrorActionPreference = "Stop"

function Read-DotEnv($Path) {
    $values = @{}
    if (-not (Test-Path $Path)) {
        throw ".env nao encontrado. Copie .env.example para .env e preencha as credenciais."
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

function Require-Value($Values, $Name) {
    if (-not $Values.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($Values[$Name])) {
        throw "$Name precisa estar configurado no .env."
    }
    return $Values[$Name]
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

$remoteMode = ($config["AYA_REMOTE_MODE"] -eq "true")
$authEnabled = ($config["AYA_AUTH_ENABLED"] -eq "true")
if (-not $remoteMode) {
    throw "AYA_REMOTE_MODE precisa ser true para iniciar o modo remoto."
}
if (-not $authEnabled) {
    throw "AYA_AUTH_ENABLED precisa ser true no modo remoto."
}

$null = Require-Value $config "AYA_AUTH_USERNAME"
$null = Require-Value $config "AYA_AUTH_PASSWORD"

python -c "import gradio, openai, rich" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Dependencias Python ausentes neste ambiente. Rode: python -m pip install -r requirements.txt"
}

$hostName = if ($config["AYA_HOST"]) { $config["AYA_HOST"] } else { "127.0.0.1" }
$port = if ($config["AYA_PORT"]) { [int]$config["AYA_PORT"] } else { 7860 }
if ($hostName -ne "127.0.0.1" -and $hostName -ne "localhost") {
    throw "Modo remoto seguro deve manter AYA_HOST=127.0.0.1 e usar Tailscale Serve."
}

$tailscale = Get-TailscaleCommand
if (-not $tailscale) {
    throw "Tailscale nao encontrado. Instale e conecte o Tailscale antes."
}

$tailscaleStatus = & $tailscale status 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Tailscale nao esta conectado. Saida: $tailscaleStatus"
}

$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "A porta local $port ja esta ocupada."
}

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 5 | Out-Null
}
catch {
    throw "Ollama nao respondeu em http://127.0.0.1:11434. Abra o Ollama antes."
}

$tailscaleIp = (& $tailscale ip -4 2>$null | Select-Object -First 1)

Write-Host ""
Write-Host "Aya remota pronta para iniciar."
Write-Host "- Gradio local: http://127.0.0.1:$port"
if ($tailscaleIp) {
    Write-Host "- IP Tailscale: $tailscaleIp"
}
Write-Host ""
Write-Host "Em outro terminal, publique somente na sua tailnet com:"
Write-Host "`"$tailscale`" serve $port"
Write-Host ""
Write-Host "Nao use tailscale funnel. Nao abra porta do roteador."
Write-Host ""

python app.py
