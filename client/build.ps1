# Build SmartKosher.exe (one-file, windowed) with PyInstaller.
#
# Usage (from the repo root):
#   powershell -ExecutionPolicy Bypass -File client\build.ps1
#
# Output: client\dist\SmartKosher.exe
# Requires: .venv with pyserial, pywebview, pyinstaller installed.

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

& $python -m PyInstaller `
    --noconfirm --onefile --windowed `
    --name SmartKosher `
    --add-data "$PSScriptRoot\ui;ui" `
    --collect-all webview `
    --distpath "$PSScriptRoot\dist" `
    --workpath "$PSScriptRoot\build" `
    --specpath "$PSScriptRoot" `
    "$PSScriptRoot\app.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\SmartKosher.exe"
