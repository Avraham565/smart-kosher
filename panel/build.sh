#!/usr/bin/env bash
# Build the panel firmware from WSL.
#
# The repo path contains '&' (smart&kosher), which breaks ESP-IDF build
# scripts (unquoted path splitting), and /mnt/c IO is slow anyway — so the
# source is rsynced to a native WSL directory and built there. Artifacts
# are copied back to panel/build_out/ in the repo.
#
# Profiles (PANEL_PROFILE env var):
#   production  (default) — clean Track A baseline; flash this to judge
#                           real visual stability.
#   diag                  — layers sdkconfig.defaults.diag (perf/sysmon/log)
#                           for numeric measurement only.
#
# Usage:  [PANEL_PROFILE=diag] bash panel/build.sh [IDF_PATH]
set -euo pipefail

REPO_PANEL="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$HOME/panel_a_build"
IDF="${1:-$HOME/lvgl_micropython/lib/esp-idf}"   # any clean v5.3+ checkout
PROFILE="${PANEL_PROFILE:-production}"

DEFAULTS="sdkconfig.defaults"
if [ "$PROFILE" = "diag" ]; then
    DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.diag"
fi
echo "Profile: $PROFILE  (SDKCONFIG_DEFAULTS=$DEFAULTS)"

rsync -a --delete \
    --exclude build/ --exclude build_out/ \
    --exclude sdkconfig --exclude sdkconfig.old \
    "$REPO_PANEL/" "$BUILD_DIR/"

source "$IDF/export.sh" > /dev/null

cd "$BUILD_DIR"
# Force sdkconfig to be regenerated from the chosen defaults every build, so
# a profile switch (or an edited *.defaults) always takes effect and no stale
# config lingers between production/diag runs.
rm -f sdkconfig
if [ ! -f build/CMakeCache.txt ]; then
    idf.py -D SDKCONFIG_DEFAULTS="$DEFAULTS" set-target esp32s3
fi
idf.py -D SDKCONFIG_DEFAULTS="$DEFAULTS" build

mkdir -p "$REPO_PANEL/build_out"
cp build/panel_a.bin \
   build/bootloader/bootloader.bin \
   build/partition_table/partition-table.bin \
   "$REPO_PANEL/build_out/"
echo
echo "Artifacts in panel/build_out — flash from Windows:"
echo "  python -m esptool --chip esp32s3 -p COM8 -b 460800 write-flash \\"
echo "    0x0 panel/build_out/bootloader.bin \\"
echo "    0x8000 panel/build_out/partition-table.bin \\"
echo "    0x10000 panel/build_out/panel_a.bin"
