#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  entrypoint.sh
#  1. Start Xvfb virtual display on :99 with GLX support (crucial!)
#  2. Expose that display over VNC on port 5900 via x11vnc
#  3. Bridge VNC to WebSocket for browser access via noVNC on port 6080
#  4. Run the game
# ─────────────────────────────────────────────────────────────────────────────
set -e

# Virtual framebuffer with GLX extension (CRUCIAL - this was missing!)
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Give Xvfb time to start properly
sleep 1

export DISPLAY=:99

# x11vnc: serve Xvfb over VNC on port 5900
x11vnc \
    -display :99 \
    -forever     \
    -nopw        \
    -rfbport 5900 \
    -bg          \
    -quiet       \
    2>/dev/null || true

# noVNC: bridge VNC → WebSocket for browser access on port 6080
websockify --web=/usr/share/novnc 6080 localhost:5900 \
    2>/dev/null &
sleep 1

# Check for interactive mode (skip build)
if [ "$1" = "bash" ] || [ "$1" = "sh" ] || [ "$1" = "interactive" ]; then
    shift
    exec /bin/bash "$@"
fi

# Always build C++ code first
cd /home/user/Documents/Claude/Projects/DND && \
cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && \
cmake --build build --parallel && \
cmake --install build

# Run the game with the provided map path or tests
if [ $# -eq 0 ]; then
    # No arguments: run tests
    cd build && ctest --verbose
else
    # Arguments provided: assume it's the map path for main.py
    python -u /home/user/Documents/Claude/Projects/DND/gui/main.py "$@"
fi

EXIT_CODE=$?
kill "$XVFB_PID" 2>/dev/null || true
exit $EXIT_CODE
