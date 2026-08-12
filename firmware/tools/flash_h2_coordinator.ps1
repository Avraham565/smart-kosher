param(
    [string]$Port     = "COM6",
    [ValidateSet("esp32h2", "esp32c6")]
    [string]$Chip     = "esp32h2",
    [int]   $Baud     = 460800,
    [string]$Python   = "C:\Python314\python.exe",
    [string]$FlashDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($FlashDir)) {
    $FlashDir = "C:\tmp\coordinator_flash_$Chip"
    if ($Chip -eq "esp32h2") { $FlashDir = "C:\tmp\h2_coordinator_flash" }
}

$bootloader  = Join-Path $FlashDir "bootloader.bin"
$partition   = Join-Path $FlashDir "partition-table.bin"
$app         = Join-Path $FlashDir "smart_kosher_h2_coordinator.bin"

foreach ($file in @($bootloader, $partition, $app)) {
    if (-not (Test-Path $file)) {
        throw "Missing flash file: $file - run build_h2_coordinator.ps1 first."
    }
}

& $Python -m esptool --chip $Chip --port $Port --baud $Baud write-flash `
    0x0      $bootloader `
    0x8000   $partition  `
    0x10000  $app

if ($LASTEXITCODE -ne 0) { throw "Flash failed with exit code $LASTEXITCODE" }

& $Python -m esptool --chip $Chip --port $Port --baud $Baud verify-flash `
    0x0      $bootloader `
    0x8000   $partition  `
    0x10000  $app

if ($LASTEXITCODE -ne 0) { throw "Verify failed with exit code $LASTEXITCODE" }

Write-Host "$Chip coordinator flash and verify complete."
