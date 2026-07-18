$ErrorActionPreference = "Stop"

function Write-Log($Message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Write-Host $line
    Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
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

$logsDir = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$script:LogPath = Join-Path $logsDir ("aya_v1_start_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$lockPath = Join-Path $logsDir "aya_v1.lock"

if (Test-Path $lockPath) {
    $oldPid = Get-Content $lockPath -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($oldPid -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
        throw "Aya ja parece estar em execucao com PID $oldPid. Encerre antes de iniciar outra instancia."
    }
    Remove-Item -LiteralPath $lockPath -Force
}

$PID | Set-Content -Path $lockPath -Encoding ASCII
try {
    Write-Log "Inicio do launcher Aya v1.0."
    $config = Read-DotEnv (Join-Path $projectRoot ".env")
    $port = if ($config["AYA_PORT"]) { [int]$config["AYA_PORT"] } else { 7860 }
    $hostName = if ($config["AYA_HOST"]) { $config["AYA_HOST"] } else { "127.0.0.1" }
    $remoteMode = ($config["AYA_REMOTE_MODE"] -eq "true")

    if ($hostName -ne "127.0.0.1" -and $hostName -ne "localhost") {
        throw "Use AYA_HOST=127.0.0.1 para a v1.0. Publique somente via Tailscale Serve."
    }

    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw "A porta local $port ja esta em uso. A Aya nao sera iniciada em duplicidade."
    }

    $ollamaReady = $false
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 5 | Out-Null
            $ollamaReady = $true
            break
        }
        catch {
            Start-Sleep -Seconds 5
        }
    }
    if (-not $ollamaReady) {
        throw "Ollama nao respondeu em 60 segundos. Abra o Ollama e tente novamente."
    }
    Write-Log "Ollama respondeu localmente."

    if ($remoteMode) {
        if ($config["AYA_AUTH_ENABLED"] -ne "true" -or -not $config["AYA_AUTH_USERNAME"] -or -not $config["AYA_AUTH_PASSWORD"]) {
            throw "Modo remoto exige AYA_AUTH_ENABLED=true, AYA_AUTH_USERNAME e AYA_AUTH_PASSWORD."
        }
        $tailscale = Get-TailscaleCommand
        if (-not $tailscale) {
            throw "Tailscale nao encontrado."
        }
        & $tailscale status *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Tailscale nao esta conectado."
        }
        Write-Log "Modo remoto habilitado via Tailscale. Nao use Funnel."
    }
    else {
        Write-Log "Modo local habilitado."
    }

    Write-Log "Iniciando app.py em 127.0.0.1:$port."
    python app.py
}
finally {
    Write-Log "Encerramento do launcher Aya v1.0."
    if (Test-Path $lockPath) {
        Remove-Item -LiteralPath $lockPath -Force
    }
}
