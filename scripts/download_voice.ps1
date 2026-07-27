param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VoicesDir = Join-Path $ProjectRoot "voices"

$VoiceFiles = @(
    @{
        Name = "pt_BR-faber-medium.onnx"
        Url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx"
    },
    @{
        Name = "pt_BR-faber-medium.onnx.json"
        Url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json"
    }
)

function Write-Step {
    param(
        [string]$Message
    )

    Write-Host "[Aya] $Message"
}

New-Item -ItemType Directory -Path $VoicesDir -Force | Out-Null

foreach ($voiceFile in $VoiceFiles) {
    $target = Join-Path $VoicesDir $voiceFile.Name

    if ((Test-Path -LiteralPath $target) -and -not $Force) {
        Write-Step "Arquivo ja existe: $($voiceFile.Name). Use -Force para baixar novamente."
        continue
    }

    Write-Step "Baixando $($voiceFile.Name)..."
    Invoke-WebRequest -Uri $voiceFile.Url -OutFile $target -UseBasicParsing

    $downloaded = Get-Item -LiteralPath $target
    if ($downloaded.Length -le 0) {
        throw "Download invalido: $($voiceFile.Name) ficou vazio."
    }

    Write-Step "OK: $($voiceFile.Name) ($($downloaded.Length) bytes)"
}

Write-Step "Voz Piper pronta em: $VoicesDir"
Write-Step "Modelo esperado pela Aya: pt_BR-faber-medium"
