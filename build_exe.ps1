$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

py -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name Romoteca `
    --version-file packaging\version_info.txt `
    main.py

$datDirectory = Join-Path $projectRoot "dist\dats"
New-Item -ItemType Directory -Force -Path $datDirectory | Out-Null
Get-ChildItem -LiteralPath (Join-Path $projectRoot "dats") -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in ".dat", ".xml" } |
    Copy-Item -Destination $datDirectory -Force

Write-Host "Ejecutable creado en: $projectRoot\dist\Romoteca.exe"
