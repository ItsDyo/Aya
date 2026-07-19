$ErrorActionPreference = "SilentlyContinue"

function Write-Item {
    param(
        [string]$Label,
        [string]$Value
    )
    Write-Host ("- {0}: {1}" -f $Label, $Value)
}

function Find-Tailscale {
    $command = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $defaultPath = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
    if (Test-Path -LiteralPath $defaultPath) {
        return $defaultPath
    }
    return $null
}

Write-Host "Status da Aya v1.0"
Write-Host ""

$ollamaOk = $false
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3
    $ollamaOk = $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
} catch {
    $ollamaOk = $false
}
Write-Item "Ollama" ($(if ($ollamaOk) { "parece ativo" } else { "nao respondeu em http://127.0.0.1:11434" }))

$portActive = $false
try {
    $connections = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
    $portActive = [bool]$connections
} catch {
    $portActive = $false
}
Write-Item "Porta 7860" ($(if ($portActive) { "em uso" } else { "livre ou Aya desligada" }))

$localOk = $false
if ($portActive) {
    try {
        $local = Invoke-WebRequest -Uri "http://127.0.0.1:7860" -UseBasicParsing -TimeoutSec 3
        $localOk = $local.StatusCode -ge 200 -and $local.StatusCode -lt 500
    } catch {
        $localOk = $false
    }
}
Write-Item "URL local" ($(if ($localOk) { "provavelmente acessivel em http://127.0.0.1:7860" } else { "nao confirmada" }))

$tailscale = Find-Tailscale
if (-not $tailscale) {
    Write-Item "Tailscale" "nao encontrado"
    Write-Item "Acesso pelo celular" "indisponivel sem Tailscale conectado"
    exit 0
}

$tailscaleStatus = & $tailscale status --json 2>$null
$connected = $false
if ($LASTEXITCODE -eq 0 -and $tailscaleStatus) {
    try {
        $json = $tailscaleStatus | ConvertFrom-Json
        $connected = [bool]$json.Self.Online
    } catch {
        $connected = $false
    }
}
Write-Item "Tailscale" ($(if ($connected) { "conectado" } else { "nao confirmado" }))

Write-Host ""
Write-Host "Tailscale Serve:"
$serveStatus = & $tailscale serve status 2>$null
if ($LASTEXITCODE -eq 0 -and $serveStatus) {
    $safeLines = $serveStatus | Where-Object { $_ -notmatch "(?i)(token|password|senha|secret|key)" }
    $safeLines | ForEach-Object { Write-Host $_ }
    $privateUrl = ($safeLines | Select-String -Pattern "https://[^\s]+\.ts\.net/?").Matches.Value | Select-Object -First 1
    if ($privateUrl) {
        Write-Host ""
        Write-Item "URL privada detectada" $privateUrl
    } else {
        Write-Host ""
        Write-Item "URL privada detectada" "nao encontrada no status do Serve"
    }
} else {
    Write-Host "- status indisponivel"
    Write-Item "Sugestao" "se a Aya estiver ligada, publique com Tailscale Serve conforme a documentacao"
}

Write-Host ""
Write-Host "Este script apenas consulta o estado atual. Ele nao inicia, encerra ou configura servicos."
