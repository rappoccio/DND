#!/bin/bash

# Debug script for RPG Battle Map
# Drops you into a bash shell in the Docker container with everything mounted
# Useful for manual builds, inspecting files, running cmake commands, etc.
# Usage: ./debug.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONTAINER_DIR="/home/user${SCRIPT_DIR#$HOME}"

echo "[*] Launching debug shell in Docker..."
echo "[*] Your home directory is mounted at /home/user"
echo "[*] Project is at: $CONTAINER_DIR"
echo "[*] Type 'exit' to quit"
echo ""

docker run --rm -it -v "$HOME":/home/user rpg_map \
  -c "cd '$CONTAINER_DIR' && \
           echo '[+] You are in: '$(pwd) && \
           echo '[+] Available commands:' && \
           echo '    cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release' && \
           echo '    cmake --build build --parallel' && \
           echo '    cmake --install build' && \
           echo '    ctest' && \
           echo '    python main.py <map.png>' && \
           echo '' && \
           bash"
