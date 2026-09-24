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

# Container path of this repo (HOME is mounted at /home/user)
CONTAINER_DIR="/home/user${SCRIPT_DIR#$HOME}"

# The address to read out to players (user procedure, step 2). The app cannot work this
# out for itself: inside the container the routing table answers 172.17.x.x, which is the
# Docker bridge and is reachable from no phone at the table. 6081 is PUBLISHED to this
# host, so the useful address is this host's, and only this host can measure it.
HOST_IP="$(ipconfig getifaddr en0 2>/dev/null \
        || ipconfig getifaddr en1 2>/dev/null \
        || hostname -I 2>/dev/null | awk '{print $1}')"
if [ -z "$HOST_IP" ]; then
    echo "[!] Could not determine this machine's LAN address; players will need it from"
    echo "    'ifconfig'/'ip addr'. The port itself is published either way."
fi

# Entrypoint is /bin/bash, so run the display+game launcher script explicitly.
# 6080 is the DM console over noVNC and initgui.sh starts x11vnc -nopw, so anyone who
# can reach it IS the DM. Bind it to loopback: the DM browses from this machine, and
# the player server (6081, M4) is the only port that ever faces the LAN — published on
# every interface on purpose, because a phone at the table has to reach it (D2, A10).
docker run --rm -v "$HOME":/home/user -p 127.0.0.1:6080:6080 -p 6081:6081 \
  -e PLAYER_ADVERTISE_HOST="$HOST_IP" rpg_map \
  /entrypoint.sh "$CONTAINER_DIR" "$CONTAINER_MAP_PATH"
