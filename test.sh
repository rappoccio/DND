#!/bin/bash
set -e

# Test script for RPG Battle Map
# Builds the extension module and runs Python unit tests

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONTAINER_DIR="/home/user${SCRIPT_DIR#$HOME}"

echo "[*] Building extension module and running tests..."
docker run --rm -v "$HOME":/home/user rpg_map \
  -c "cd '$CONTAINER_DIR' && ./compile.sh && python3 tests/run_all_tests.py"

echo "[+] All tests passed!"
