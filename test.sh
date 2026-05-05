#!/bin/bash
set -e

# Test script for RPG Battle Map
# Runs unit tests via Docker

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[*] Building and running tests..."
docker run --rm -v "$HOME":/home/user rpg_map \
  bash -c "cd /home/user/Documents/Claude/Projects/DND && \
           cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && \
           cmake --build build --parallel && \
           cmake --install build && \
           cd build && ctest --verbose"

echo "[+] Tests passed!"
