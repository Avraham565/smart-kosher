# Deploy products/panel/device to a CrowPanel running lvgl_micropython.
#
# DMA-safe procedure (learned the hard way — see memory lvgl-crowpanel): LVGL's
# RGB DMA keeps running in the background even after main.py crashes to the REPL,
# and `mpremote cp` then dies mid-transfer (~44%) racing the DMA. So we first
# delete main.py and reset to a clean board (no UI, no DMA), copy everything,
# then drop main.py in last and reset.
#
# Usage:  .\deploy.ps1            (finds the panel)
#         .\deploy.ps1 -Port COM8  (override)
param(
    [string]$Port
)

$ErrorActionPreference = "Stop"
$here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$device   = Join-Path $here "..\device"
# host/ -> panel/ -> products/ -> repo root.
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $here))
$pkgSrc   = Join-Path $repoRoot "src\smart_kosher"

if (-not $Port) {
    # find_panel() is the one place that knows the panel's USB id, and the
    # three hwtest runners already call it. This script was the only one in the
    # directory still demanding -Port, and the COM7<->COM8 jump it could not
    # follow is what broke a deploy on 2026-08-24.
    #
    # It is asked rather than reimplemented: PowerShell cannot import Python,
    # and a second copy of a VID/PID in another language is exactly how the two
    # sides drift apart without either being wrong on its own.
    $finder = "import sys; sys.path.insert(0, r'{0}'); from run_common import find_panel; print(find_panel() or '')" -f $here
    $Port = (& python -c $finder | Out-String).Trim()
    if (-not $Port) {
        throw "No panel found (CH340 1A86:7522). Is its USB connected? Pass -Port to override."
    }
    Write-Host "panel on $Port"
}

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
Get-ChildItem (Join-Path $device "fonts\*.bin") | ForEach-Object {
    Write-Host "   font ->" $_.Name
    Mpr cp $_.FullName (":" + $_.Name)
}

Write-Host "== 3) copy UI modules to board root =="
# The payload is the directory, not a list. This was 29 hand-maintained names,
# and the failure mode was silent: uart_tap.py is imported unconditionally by
# main.py, so omitting it bricked the boot, and nothing but a board could say
# so. device/ now means "this is what gets flashed" -- adding a module there is
# the whole change, and a module that is not there is not part of the product.
# main.py is excluded here and copied last, in step 4.
# (scheduler.py is not a root module any more: it moved into the brain package
# at smart_kosher/application/scheduler.py and ships with the /lib copy below.)
$modules = Get-ChildItem (Join-Path $device "*.py") -File |
           Where-Object { $_.Name -ne "main.py" } |
           Sort-Object Name
if ($modules.Count -eq 0) { throw "no modules found in $device -- wrong path?" }
foreach ($m in $modules) {
    Write-Host "   module ->" $m.Name
    Mpr cp $m.FullName (":" + $m.Name)
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

Write-Host "== 3c) remove modules that moved out of the board root =="
# A board flashed before 2026-08-05 has /scheduler.py at the root. It now lives
# in the brain package (/lib/smart_kosher/application/) and main.py imports it
# from there, so the root copy is dead -- but nothing deletes it: clean_board
# only removes main.py, and a copy never removes what it does not overwrite. A
# stale module that still imports and still runs is exactly what wastes an hour
# at 3am.
foreach ($stale in @("scheduler.py")) {
    try { Mpr rm (":" + $stale); Write-Host "   removed stale ->" $stale }
    catch { }   # not there: the normal case on a clean board
}

Write-Host "== 4) main.py last, then reset =="
Mpr cp (Join-Path $device "main.py") ":main.py"
Mpr reset
Write-Host "== done. Watch the panel; read logs with: python -m mpremote connect $Port =="
