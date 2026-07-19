$ErrorActionPreference = "SilentlyContinue"

$portActive = $false
try {
    $connections = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
    $portActive = [bool]$connections
} catch {
    $portActive = $false
}

if ($portActive) {
    Write-Host "Abrindo Aya em http://127.0.0.1:7860"
    Start-Process "http://127.0.0.1:7860"
    exit 0
}

Write-Host "A Aya nao parece estar ligada. Execute primeiro o atalho Iniciar Aya."
exit 1
