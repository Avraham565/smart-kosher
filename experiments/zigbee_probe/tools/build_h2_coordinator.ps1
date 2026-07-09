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

$wslBuild   = Convert-ToWslPath $BuildRoot
$wslCommand = "source ~/esp/esp-idf/export.sh && cd $wslBuild && idf.py set-target $Target && idf.py build"

$ErrorActionPreference = "Continue"
wsl bash -lc $wslCommand
$buildExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($buildExitCode -ne 0) {
    throw "ESP-IDF build failed with exit code $buildExitCode"
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
