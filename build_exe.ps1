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

Write-Host "Ejecutable creado en: $projectRoot\dist\Romoteca.exe"

