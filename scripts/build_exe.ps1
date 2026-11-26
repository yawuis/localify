$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name localify `
    --paths src `
    scripts\entry_gui.py

Write-Output "Built standalone executable: $repoRoot\dist\localify.exe"
