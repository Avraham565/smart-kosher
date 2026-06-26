param(
    [string]$Port     = "COM6",
    [int]   $Baud     = 460800,
    [string]$Python   = "C:\Python314\python.exe",
    [string]$FlashDir = "C:\tmp\h2_coordinator_flash"
)

$ErrorActionPreference = "Stop"

$bootloader  = Join-Path $FlashDir "bootloader.bin"
$partition   = Join-Path $FlashDir "partition-table.bin"
$app         = Join-Path $FlashDir "smart_kosher_h2_coordinator.bin"

foreach ($file in @($bootloader, $partition, $app)) {
    if (-not (Test-Path $file)) {
        throw "Missing flash file: $file - run build_h2_coordinator.ps1 first."
    }
}

& $Python -m esptool --chip esp32h2 --port $Port --baud $Baud write-flash `
    0x0      $bootloader `
    0x8000   $partition  `
    0x10000  $app

if ($LASTEXITCODE -ne 0) { throw "Flash failed with exit code $LASTEXITCODE" }

& $Python -m esptool --chip esp32h2 --port $Port --baud $Baud verify-flash `
    0x0      $bootloader `
    0x8000   $partition  `
    0x10000  $app

if ($LASTEXITCODE -ne 0) { throw "Verify failed with exit code $LASTEXITCODE" }

Write-Host "H2 coordinator flash and verify complete."
