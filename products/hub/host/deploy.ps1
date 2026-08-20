# Deploy Smart Kosher to the AtomS3 Lite over mpremote.
#
# Usage (from the repo root, device connected over USB):
#   powershell -ExecutionPolicy Bypass -File products\hub\host\deploy.ps1
#   powershell ... deploy.ps1 -Port COM10      # pin a specific port
#   powershell ... deploy.ps1 -WithMicrodot    # first deploy only
#
# Notes from the bring-up (see memory/atoms3_lite_bringup.md):
# - The COM port CHANGES between bootloader (PID 1001) and MicroPython
#   (PID 4001). If auto-connect fails, check: Get-PnpDevice -Class Ports
# - Connecting mpremote interrupts a running server — that is fine here,
#   we want it stopped before copying.
# - If mpremote cannot talk at all: unplug USB, plug back in (power cycle).

param(
    [string]$Port = "",
    [string]$Python = "",
    [switch]$WithMicrodot,
    [switch]$StageOnly     # stop after staging (inspect $env:TEMP\sk_atoms3_stage)
)

$ErrorActionPreference = "Stop"
# host/ -> hub/ -> products/ -> repo root.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$device = Join-Path $PSScriptRoot "..\device"
$stage = Join-Path $env:TEMP "sk_atoms3_stage"

# Prefer the repo venv (has mpy-cross + mpremote); `python -m` also dodges
# Application Control policies that block the .exe entry-point shims.
if ($Python -eq "") {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { $Python = $venvPython } else { $Python = "python" }
}

$mp = "& `"$Python`" -m mpremote"
if ($Port -ne "") { $mp = "$mp connect $Port" }

# $ErrorActionPreference = "Stop" does not apply to native executables in
# PowerShell 5.1 -- which is the shell this script's own header tells you to
# run it under -- so a failing mpremote used to print its error and let the
# script sail on to the next step. The worst shape of that is silent: a copy
# fails, the reset still happens, the script prints "Done", and the board comes
# up running whatever mixture of old and new files it happens to hold.
# The mpy-cross loop below already checked $LASTEXITCODE; mpremote never did.
function Invoke-Mp($command, $what) {
    Invoke-Expression $command
    if ($LASTEXITCODE -ne 0) {
        throw "$what failed (mpremote exit $LASTEXITCODE)"
    }
}

Write-Host "== staging clean copy (no __pycache__) =="
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item -Recurse (Join-Path $repoRoot "src\smart_kosher") $stage
Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Write-Host "== cross-compiling to .mpy (big RAM saver on the no-PSRAM AtomS3) =="
$hasMpyCross = $false
try {
    & $Python -m mpy_cross --version | Out-Null
    if ($LASTEXITCODE -eq 0) { $hasMpyCross = $true }
} catch {}
if ($hasMpyCross) {
    Get-ChildItem "$stage\smart_kosher" -Recurse -File -Filter "*.py" | ForEach-Object {
        & $Python -m mpy_cross $_.FullName
        if ($LASTEXITCODE -ne 0) { throw "mpy-cross failed on $($_.FullName)" }
        Remove-Item $_.FullName
    }
    Write-Host "  compiled package to .mpy (device imports them like .py)"
} else {
    Write-Host "  mpy-cross not found - deploying as .py source." -ForegroundColor Yellow
    Write-Host "  Install with: pip install `"mpy-cross==1.24.*`"  (must match device MicroPython)" -ForegroundColor Yellow
}

if ($StageOnly) {
    Write-Host "== stage-only: skipping device steps. Staged at: $stage =="
    exit 0
}

Write-Host "== removing old package on device (avoids stale .py/.mpy shadowing) =="
Invoke-Mp "$mp run `"$device\device_cleanup.py`"" "device cleanup"

Write-Host "== copying smart_kosher package to /lib =="
# /lib must exist first. mpremote copies *into* the destination only when it is
# already a directory; on a fresh board it treats the missing path as the
# destination name instead, so the package lands as /lib/application/... rather
# than /lib/smart_kosher/application/... . The board then fails its import at
# boot and reset-loops every five seconds -- with no USB channel to recover
# through, because the channel is the thing that failed to import.
# products/panel/host/deploy.ps1 has carried this line for the same reason.
# Deliberately unchecked, unlike every call below: on a board that has been
# deployed before this fails with "already exists", which is the normal case.
Invoke-Expression "$mp fs mkdir :/lib" 2>&1 | Out-Null
Invoke-Mp "$mp fs cp -r `"$stage\smart_kosher`" :/lib/" "copying smart_kosher"

if ($WithMicrodot) {
    Write-Host "== copying microdot (first deploy) =="
    $microdot = Join-Path $env:TEMP "sk_microdot_stage"
    if (Test-Path $microdot) { Remove-Item -Recurse -Force $microdot }
    New-Item -ItemType Directory -Force "$microdot\microdot" | Out-Null
    $src = & $Python -c "import microdot, os; print(os.path.dirname(microdot.__file__))"
    Copy-Item "$src\__init__.py" "$microdot\microdot\"
    Copy-Item "$src\microdot.py" "$microdot\microdot\"
    Invoke-Mp "$mp fs cp -r `"$microdot\microdot`" :/lib/" "copying microdot"
}

# main.py last, after every module it imports is already on the device.
Write-Host "== copying main.py =="
Invoke-Mp "$mp fs cp `"$device\main.py`" :main.py" "copying main.py"

Write-Host "== resetting device =="
Invoke-Mp "$mp reset" "device reset"

Write-Host ""
Write-Host "Done. Now:"
Write-Host "  1. Provision WiFi over the USB serial channel (115200 baud, one"
Write-Host "     JSON per line):"
Write-Host "       {""op"": ""wifi.provision"", ""params"": {""ssid"": ""..."", ""password"": ""...""}}"
Write-Host "       {""op"": ""system.reboot""}"
Write-Host "     The boot log prints the IP once the hub joins the network."
Write-Host "  2. Check http://<device-ip>/api/status - look at memory.free"
