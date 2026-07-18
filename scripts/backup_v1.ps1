$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path $projectRoot "backups"
$staging = Join-Path $backupRoot "aya_v1_backup_$stamp"
$archive = Join-Path $backupRoot "aya_v1_backup_$stamp.zip"

New-Item -ItemType Directory -Force -Path $staging | Out-Null

$items = @(
    "aya",
    "docs",
    "scripts",
    "tests",
    "app.py",
    "main.py",
    "README.md",
    "requirements.txt",
    ".env.example",
    "voz.py"
)

foreach ($item in $items) {
    if (Test-Path $item) {
        Copy-Item -Path $item -Destination $staging -Recurse -Force
    }
}

foreach ($item in @("data_local\aya.sqlite", "data_local\study_ai.db", "data_local\historico_aya.json")) {
    if (Test-Path $item) {
        $targetDir = Join-Path $staging (Split-Path $item -Parent)
        New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        Copy-Item -Path $item -Destination $targetDir -Force
    }
}

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $archive -Force
Remove-Item -LiteralPath $staging -Recurse -Force

Write-Host "Backup local criado: $archive"
Write-Host "Nao inclui .env, tokens, modelos Ollama, worktrees temporarios ou caches."
