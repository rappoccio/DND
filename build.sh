#!/bin/bash
set -e

# Build script for RPG Battle Map
# Builds the C++ extension inside the existing rpg_map image, with volume mounts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The rpg_map image is NOT built here. The user builds it separately, in another
# directory, only when the Dockerfile changes; this script assumes it exists.

CONTAINER_DIR="/home/user${SCRIPT_DIR#$HOME}"

echo "[*] Building C++ extension (cmake + ninja)..."
docker run --rm -v "$HOME":/home/user rpg_map \
  -c "cd '$CONTAINER_DIR' && ./compile.sh"

echo "[+] Build complete! Extension installed to gui/"
