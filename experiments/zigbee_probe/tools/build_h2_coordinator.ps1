param(
    [ValidateSet("esp32h2", "esp32c6")]
    [string]$Target    = "esp32h2",
    [string]$BuildRoot = "",
    [string]$FlashOut  = ""
)

if ([string]::IsNullOrWhiteSpace($FlashOut)) {
    $FlashOut = "C:\tmp\coordinator_flash_$Target"
    if ($Target -eq "esp32h2") { $FlashOut = "C:\tmp\h2_coordinator_flash" }
}

$ErrorActionPreference = "Stop"

$experimentRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot     = Join-Path $experimentRoot "h2_coordinator_firmware"

function Convert-ToWslPath([string]$Path) {
    $full  = [System.IO.Path]::GetFullPath($Path)
    $drive = $full.Substring(0, 1).ToLowerInvariant()
    $tail  = $full.Substring(3).Replace('\', '/')
    return "/mnt/$drive/$tail"
}

if ([string]::IsNullOrWhiteSpace($BuildRoot)) {
    $stamp     = Get-Date -Format "yyyyMMdd_HHmmss"
    $BuildRoot = "C:\tmp\zigbee_coord_${Target}_build_$stamp"
} elseif (Test-Path $BuildRoot) {
    throw "BuildRoot already exists: $BuildRoot"
}
New-Item -ItemType Directory -Force $BuildRoot | Out-Null

Copy-Item -Force  (Join-Path $sourceRoot "CMakeLists.txt")    $BuildRoot
Copy-Item -Force  (Join-Path $sourceRoot "sdkconfig.defaults*") $BuildRoot
Copy-Item -Force  (Join-Path $sourceRoot "partitions.csv")     $BuildRoot
Copy-Item -Recurse -Force (Join-Path $sourceRoot "main")       $BuildRoot

# Carry the dependency lock into the throwaway build dir, and back out again
# afterwards. Because this script builds in a fresh C:\tmp copy, the lock the
# component manager writes used to be discarded with it -- so every build
# re-resolved esp-zigbee-lib from the registry and nothing recorded which
# version the flashed firmware was actually built from. Round-tripping it makes
# a dependency change show up as a diff in git instead of silently.
$lockName   = "dependencies.lock"
$sourceLock = Join-Path $sourceRoot $lockName
if (Test-Path $sourceLock) { Copy-Item -Force $sourceLock $BuildRoot }

$wslBuild = Convert-ToWslPath $BuildRoot
# Announce the toolchain before building. idf_component.yml can only reject an
# incompatible IDF, never choose one -- the version that actually compiles this
# firmware is whatever export.sh here happens to set up. Printing it makes a
# silently upgraded toolchain visible at the top of the log instead of only
# afterwards, in the dependencies.lock diff.
$wslCommand = "source ~/esp/esp-idf/export.sh && echo '--- toolchain ---' && idf.py --version && cd $wslBuild && idf.py set-target $Target && idf.py build"

$ErrorActionPreference = "Continue"
wsl bash -lc $wslCommand
$buildExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($buildExitCode -ne 0) {
    throw "ESP-IDF build failed with exit code $buildExitCode"
}

$builtLock = Join-Path $BuildRoot $lockName
if (Test-Path $builtLock) {
    Copy-Item -Force $builtLock $sourceLock
    Write-Host "dependency lock updated: $sourceLock (review the git diff)"
}

New-Item -ItemType Directory -Force $FlashOut | Out-Null
Copy-Item -Force (Join-Path $BuildRoot "build\bootloader\bootloader.bin")         $FlashOut
Copy-Item -Force (Join-Path $BuildRoot "build\partition_table\partition-table.bin") $FlashOut
Copy-Item -Force (Join-Path $BuildRoot "build\smart_kosher_h2_coordinator.bin")   $FlashOut

Write-Host "$Target coordinator build complete."
Write-Host "Flash files:"
Write-Host "  $FlashOut\bootloader.bin"
Write-Host "  $FlashOut\partition-table.bin"
Write-Host "  $FlashOut\smart_kosher_h2_coordinator.bin"
