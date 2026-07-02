#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  initgui.sh  (installed inside the image as /entrypoint.sh)
#  1. Start Xvfb virtual display on :99 with GLX support (crucial!)
#  2. Expose that display over VNC on port 5900 via x11vnc
#  3. Bridge VNC to WebSocket for browser access via noVNC on port 6080
#  4. Run the game
#
#  Args (passed by run.sh):  $1 = container repo dir   $2 = map image path
#  With no args it just keeps the display alive for interactive use.
# ─────────────────────────────────────────────────────────────────────────────
set -e

REPO_DIR="${1:-/home/user/Claude/DND}"
MAP_PATH="$2"

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

# ── 4. Run the game ──────────────────────────────────────────────────────────
cd "$REPO_DIR"
if [ -n "$MAP_PATH" ]; then
    exec python3 gui/main.py "$MAP_PATH"
else
    # No map given: keep the display services alive for interactive use
    wait $XVFB_PID
fi
