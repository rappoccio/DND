#!/bin/bash
set -e

# Build script for RPG Battle Map
# Builds the C++ extension inside Docker with volume mounts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[*] Building Docker image..."
docker build -t rpg_map "$SCRIPT_DIR"

CONTAINER_DIR="/home/user${SCRIPT_DIR#$HOME}"

echo "[*] Building C++ extension (cmake + ninja)..."
docker run --rm -v "$HOME":/home/user rpg_map \
  -c "cd '$CONTAINER_DIR' && ./compile.sh"

echo "[+] Build complete! Extension installed to gui/"
