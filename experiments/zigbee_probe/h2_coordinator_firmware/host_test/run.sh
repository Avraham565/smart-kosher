#!/usr/bin/env bash
# Build and run the coordinator's host-side tests. Plain gcc -- no ESP-IDF, no
# framework to install, so this runs anywhere (including WSL alongside the
# firmware build).
set -euo pipefail
cd "$(dirname "$0")"

gcc -std=c11 -Wall -Wextra -Werror -O1 \
    -I../main \
    -o /tmp/h2_host_test \
    test_main.c ../main/protocol.c ../main/txn.c

/tmp/h2_host_test
