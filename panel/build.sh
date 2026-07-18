#!/usr/bin/env bash
# Build the panel firmware from WSL.
#
# The repo path contains '&' (smart&kosher), which breaks ESP-IDF build
# scripts (unquoted path splitting), and /mnt/c IO is slow anyway — so the
# source is rsynced to a native WSL directory and built there. Artifacts
# are copied back to panel/build_out/ in the repo.
#
# Usage:  bash panel/build.sh [IDF_PATH]
set -euo pipefail

REPO_PANEL="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$HOME/panel_a_build"
IDF="${1:-$HOME/lvgl_micropython/lib/esp-idf}"   # any clean v5.3+ checkout

rsync -a --delete \
    --exclude build/ --exclude build_out/ --exclude sdkconfig.old \
    "$REPO_PANEL/" "$BUILD_DIR/"

source "$IDF/export.sh" > /dev/null

cd "$BUILD_DIR"
if [ ! -f build/CMakeCache.txt ]; then
    idf.py set-target esp32s3
fi
idf.py build

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
