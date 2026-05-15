#!/bin/bash
set -e

# Test script for RPG Battle Map
# Builds the extension module and runs Python unit tests

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[*] Building extension module and running tests..."
docker run --rm -v "$HOME":/home/user rpg_map \
  bash -c "cd /home/user/Documents/Claude/Projects/DND && \
           cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && \
           cmake --build build --parallel && \
           cmake --install build && \
           cd gui && python3 run_all_tests.py"

echo "[+] All tests passed!"
