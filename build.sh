#!/bin/bash
set -e

# Build script for RPG Battle Map
# Builds the C++ extension inside Docker with volume mounts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[*] Building Docker image..."
docker build -t rpg_map "$SCRIPT_DIR"

echo "[*] Building C++ extension (cmake + ninja)..."
docker run --rm -v "$HOME":/home/user rpg_map \
  bash -c "cd /home/user/Documents/Claude/Projects/DND && ./compile.sh"

echo "[+] Build complete! Extension installed to gui/"
