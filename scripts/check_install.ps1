$ErrorActionPreference = "Continue"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$script:Errors = 0
$script:Warnings = 0

function Write-Check {
    param(
        [ValidateSet("OK", "AVISO", "ERRO")]
        [string]$Status,
        [string]$Name,
        [string]$Detail
    )

    Write-Host ("[{0}] {1} - {2}" -f $Status, $Name, $Detail)

    if ($Status -eq "ERRO") {
        $script:Errors += 1
    }
    elseif ($Status -eq "AVISO") {
        $script:Warnings += 1
    }
}

function Test-CommandAvailable {
    param([string]$Name)

    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-FilePresent {
    param(
        [string]$RelativePath,
        [string]$Description,
        [switch]$WarningOnly
    )

    $path = Join-Path $ProjectRoot $RelativePath
    if (Test-Path -LiteralPath $path) {
        Write-Check "OK" $Description $RelativePath
        return
    }

    if ($WarningOnly) {
        Write-Check "AVISO" $Description "$RelativePath nao encontrado"
    }
    else {
        Write-Check "ERRO" $Description "$RelativePath nao encontrado"
    }
}

Write-Host "Diagnostico de instalacao da Aya v1"
Write-Host "Raiz: $ProjectRoot"
Write-Host ""

if (Test-CommandAvailable "git") {
    $gitRoot = git -C $ProjectRoot rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Check "OK" "Git" "repositorio detectado em $gitRoot"
    }
    else {
        Write-Check "AVISO" "Git" "Git existe, mas esta pasta nao parece um repositorio"
    }
}
else {
    Write-Check "AVISO" "Git" "comando git nao encontrado"
}

if (Test-CommandAvailable "python") {
    $pythonVersion = python --version 2>&1
    Write-Check "OK" "Python" $pythonVersion

    python -m pip --version *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Check "OK" "pip" "disponivel"
    }
    else {
        Write-Check "ERRO" "pip" "python -m pip nao respondeu corretamente"
    }

    foreach ($package in @("gradio", "openai", "rich", "piper-tts")) {
        python -m pip show $package *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Check "OK" "Pacote Python" $package
        }
        else {
            Write-Check "ERRO" "Pacote Python" "$package ausente; execute python -m pip install -r requirements.txt"
        }
    }
}
else {
    Write-Check "ERRO" "Python" "comando python nao encontrado"
}

Test-FilePresent ".env.example" ".env.example"
Test-FilePresent ".env" ".env local" -WarningOnly
Test-FilePresent "requirements.txt" "requirements.txt"
Test-FilePresent "README.md" "README.md"
Test-FilePresent "docs\uso_rapido_v1.md" "documentacao de uso rapido"
Test-FilePresent "docs\instalacao_limpa.md" "documentacao de instalacao limpa"

foreach ($scriptPath in @(
        "scripts\start_v1.ps1",
        "scripts\open_v1.ps1",
        "scripts\status_v1.ps1",
        "scripts\download_voice.ps1"
    )) {
    Test-FilePresent $scriptPath "script necessario"
}

Test-FilePresent "voices\pt_BR-faber-medium.onnx" "voz Piper modelo" -WarningOnly
Test-FilePresent "voices\pt_BR-faber-medium.onnx.json" "voz Piper configuracao" -WarningOnly

if (Test-CommandAvailable "ollama") {
    $ollamaList = ollama list 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Check "OK" "Ollama" "comando respondeu"

        foreach ($model in @("llama3.2", "gemma2:2b")) {
            if ($ollamaList -match [regex]::Escape($model)) {
                Write-Check "OK" "Modelo Ollama" $model
            }
            else {
                Write-Check "ERRO" "Modelo Ollama" "$model ausente; execute ollama pull $model"
            }
        }

        if ($ollamaList -match [regex]::Escape("embeddinggemma")) {
            Write-Check "OK" "Modelo Ollama opcional" "embeddinggemma"
        }
        else {
            Write-Check "AVISO" "Modelo Ollama opcional" "embeddinggemma ausente; necessario para embeddings locais"
        }
    }
    else {
        Write-Check "AVISO" "Ollama" "comando encontrado, mas o servico nao respondeu"
    }
}
else {
    Write-Check "ERRO" "Ollama" "comando ollama nao encontrado"
}

if (Test-CommandAvailable "tailscale") {
    $tailscaleStatus = tailscale status --json 2>$null
    if ($LASTEXITCODE -eq 0 -and $tailscaleStatus) {
        Write-Check "OK" "Tailscale" "conectividade local parece disponivel"
    }
    else {
        Write-Check "AVISO" "Tailscale" "comando existe, mas nao respondeu conectado"
    }
}
else {
    Write-Check "AVISO" "Tailscale" "opcional; necessario apenas para acesso pelo celular"
}

Write-Host ""
Write-Host ("Resumo: {0} erro(s), {1} aviso(s)." -f $script:Errors, $script:Warnings)

if ($script:Errors -gt 0) {
    exit 1
}

exit 0
