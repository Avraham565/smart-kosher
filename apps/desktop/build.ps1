# Build SmartKosher.exe (one-file, windowed) with PyInstaller.
#
# Usage (from the repo root):
#   powershell -ExecutionPolicy Bypass -File apps\desktop\build.ps1
#
# Output: apps\desktop\dist\SmartKosher.exe
# Requires: .venv with pyserial, pywebview, pyinstaller installed.

$ErrorActionPreference = "Stop"
# desktop/ -> apps/ -> repo root.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# --paths src: bridge.py imports smart_kosher.web.route_table, the shared
# table the hub registers its own HTTP routes from. Without this the exe
# builds and then fails on the first request.
& $python -m PyInstaller `
    --noconfirm --onefile --windowed `
    --name SmartKosher `
    --add-data "$PSScriptRoot\ui;ui" `
    --paths "$repoRoot\src" `
    --collect-all webview `
    --distpath "$PSScriptRoot\dist" `
    --workpath "$PSScriptRoot\build" `
    --specpath "$PSScriptRoot" `
    "$PSScriptRoot\app.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\SmartKosher.exe"
