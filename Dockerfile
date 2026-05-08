# ─────────────────────────────────────────────────────────────────────────────
#  RPG Battle Map – Docker build with volume mounts
#
#  Build (from project root):
#    docker build -t rpg_map .
#
#  Run (build + test):
#    docker run --rm -v /Users/rappoccio:/home/user \
#      rpg_map
#
#  Run (build only, no tests):
#    docker run --rm -v /Users/rappoccio:/home/user \
#      rpg_map cmake --build /home/user/Documents/Claude/Projects/DND/build --parallel
#
#  Run GUI:
#    docker run --rm -v /Users/rappoccio:/home/user -p 6080:6080 \
#      rpg_map python /home/user/Documents/Claude/Projects/DND/main.py /path/to/map.png
#
#  The /home/user mount gives the container access to all your source files.
#  Build artifacts go into the mounted directory for easy access.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV XDG_RUNTIME_DIR=/tmp/xdg_runtime
ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1
ENV SDL_AUDIODRIVER=dummy

# Install build tools, dependencies, display server, VNC, and noVNC
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    g++ \
    cmake \
    ninja-build \
    git \
    pkg-config \
    libopencv-dev \
    python3-dev \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    libx11-6 \
    libxext6 \
    libxrandr2 \
    libxcursor1 \
    libxi6 \
    libxfixes3 \
    libglib2.0-0 \
    libstdc++6 \
    libgl1-mesa-dri \
    libglx-mesa0 \
    libsdl2-2.0-0 \
    && pip install --no-cache-dir Pillow pygame \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /tmp/xdg_runtime && chmod 700 /tmp/xdg_runtime

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set working directory (will be overridden by mount)
WORKDIR /workspace

# Use entrypoint for GUI
ENTRYPOINT ["/entrypoint.sh"]
