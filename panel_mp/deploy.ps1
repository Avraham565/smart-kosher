# Deploy panel_mp to a CrowPanel running lvgl_micropython.
#
# DMA-safe procedure (learned the hard way — see memory lvgl-crowpanel): LVGL's
# RGB DMA keeps running in the background even after main.py crashes to the REPL,
# and `mpremote cp` then dies mid-transfer (~44%) racing the DMA. So we first
# delete main.py and reset to a clean board (no UI, no DMA), copy everything,
# then drop main.py in last and reset.
#
# Usage:  .\deploy.ps1 -Port COM8
param(
    [Parameter(Mandatory = $true)][string]$Port
)

$ErrorActionPreference = "Stop"
$here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $here
$pkgSrc   = Join-Path $repoRoot "src\smart_kosher"
$mpr      = "python", "-m", "mpremote", "connect", $Port

function Mpr { & $mpr[0] $mpr[1..($mpr.Length - 1)] @args }

Write-Host "== 1) clean board (interrupt main.py before DMA starts, remove it) =="
# A board already rendering keeps the RGB DMA running even at the REPL, and any
# file transfer then races it and corrupts the VFS (LoadProhibited). clean_board
# hardware-resets and Ctrl-C's through the boot window to stop main.py *before*
# display.init(), so the copies below run on a DMA-free board.
& $mpr[0] (Join-Path $here "clean_board.py") $Port
if ($LASTEXITCODE -ne 0) { throw "clean_board failed to reach a clean state on $Port" }
Start-Sleep -Seconds 1

Write-Host "== 2) copy fonts to board root (binfont path is 'S:<name>') =="
Get-ChildItem (Join-Path $here "fonts\*.bin") | ForEach-Object {
    Write-Host "   font ->" $_.Name
    Mpr cp $_.FullName (":" + $_.Name)
}

Write-Host "== 3) copy UI modules to board root =="
$modules = "theme.py", "widgets.py", "reactive.py", "store.py", "hebdate.py",
           "clock.py", "shell.py", "pages.py", "keyboard.py", "text_input.py",
           "settime.py", "zmanim_page.py", "toast.py", "dev_common.py",
           "zone_picker.py", "rooms_page.py", "room_page.py", "device_page.py",
           "sched_labels.py", "sched_describe.py", "schedules_page.py",
           "schedule_add.py", "display.py", "ui_home.py", "lvgl_loop.py",
           "bridge.py", "brain.py"
foreach ($m in $modules) {
    Write-Host "   module ->" $m
    Mpr cp (Join-Path $here $m) (":" + $m)
}

Write-Host "== 3b) copy brain package to /lib/smart_kosher =="
# The brain (src/smart_kosher) is imported as a package from /lib. Ensure /lib
# exists, then recursively copy the package. /data is created by the brain at
# boot (JsonRepository), and settings fall back to code defaults, so no seeding
# is required for a first run.
#
# Stage a copy without __pycache__ first: MicroPython ignores CPython .pyc, so
# shipping them just wastes flash and clutters the tree.
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("sk_pkg_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $stage | Out-Null
try {
    Copy-Item -Recurse -Force $pkgSrc (Join-Path $stage "smart_kosher")
    Get-ChildItem -Path $stage -Recurse -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force
    try { Mpr mkdir :/lib } catch {}   # ignore "already exists"
    Mpr cp -r (Join-Path $stage "smart_kosher") ":/lib/"
} finally {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
}

Write-Host "== 4) main.py last, then reset =="
Mpr cp (Join-Path $here "main.py") ":main.py"
Mpr reset
Write-Host "== done. Watch the panel; read logs with: python -m mpremote connect $Port =="
