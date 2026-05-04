#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  entrypoint.sh
#  1. Start an in-container Xvfb virtual display on :99
#     (no real GPU, no GLX probe against XQuartz → no BadValue crash)
#  2. Expose that display over VNC on port 5900 via x11vnc
#     (no password for local dev; add -usepw for production)
#  3. Run the game
# ─────────────────────────────────────────────────────────────────────────────
set -e

# Virtual framebuffer: 24-bit colour, GLX extension enabled for Mesa software
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Give Xvfb a moment to start
sleep 0.5

export DISPLAY=:99

# x11vnc: serve Xvfb over VNC on port 5900 (no password)
x11vnc \
    -display :99 \
    -forever     \
    -nopw        \
    -rfbport 5900 \
    -bg          \
    -quiet       \
    2>/dev/null || true

# noVNC: bridge VNC → WebSocket so any browser can view on port 6080
websockify --web=/usr/share/novnc 6080 localhost:5900 &
2>/dev/null || true

# Run the game, forwarding all arguments (-u = unbuffered stdout/stderr so
# print() debug lines appear in `docker logs` immediately, not at exit)
python -u /app/main.py "$@"
EXIT_CODE=$?

kill "$XVFB_PID" 2>/dev/null || true
exit $EXIT_CODE
