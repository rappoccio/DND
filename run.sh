#!/bin/bash

# Run script for RPG Battle Map GUI
# Launches the battle map viewer with a map image
# Usage: ./run.sh /path/to/map.png

if [ $# -eq 0 ]; then
    echo "Usage: $0 <map_image.png>"
    echo ""
    echo "Examples:"
    echo "  $0 maps/TestDNDMap.png"
    echo "  $0 /absolute/path/to/map.png"
    exit 1
fi

MAP_PATH="$1"

# Verify the map file exists
if [ ! -f "$MAP_PATH" ]; then
    echo "Error: Map file not found: $MAP_PATH"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Convert relative path to absolute path
if [[ ! "$MAP_PATH" = /* ]]; then
    MAP_PATH="$(cd "$(dirname "$MAP_PATH")" && pwd)/$(basename "$MAP_PATH")"
fi

# Convert host path to container path (HOME is mounted at /home/user)
CONTAINER_MAP_PATH="$MAP_PATH"
if [[ "$MAP_PATH" = "$HOME"* ]]; then
    CONTAINER_MAP_PATH="/home/user${MAP_PATH#$HOME}"
fi

echo "[*] Building Docker image (if needed)..."
docker build -t rpg_map "$SCRIPT_DIR" > /dev/null 2>&1

echo "[*] Launching RPG Battle Map GUI..."
echo "[*] Map: $MAP_PATH"
echo "[*] Access via browser: http://localhost:6080/vnc.html"
echo "[*] Press Ctrl+C to stop the container"
echo ""

docker run --rm -v "$HOME":/home/user -p 6080:6080 rpg_map \
  bash -c "Xvfb :99 -screen 0 1280x1024x24 -ac > /dev/null 2>&1 &
           sleep 1
           x11vnc -display :99 -forever -nopw > /dev/null 2>&1 &
           sleep 1
           websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 > /dev/null 2>&1 &
           sleep 1
           cd /home/user/Documents/Claude/Projects/DND && \
           python gui/main.py '$CONTAINER_MAP_PATH'"
