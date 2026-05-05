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
    && pip install --no-cache-dir Pillow pygame \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /tmp/xdg_runtime && chmod 700 /tmp/xdg_runtime

# Set working directory (will be overridden by mount)
WORKDIR /workspace

# Default command: configure, build, and run tests
CMD ["bash", "-c", "\
  cd /home/user/Documents/Claude/Projects/DND && \
  cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && \
  cmake --build build --parallel && \
  cmake --install build && \
  cd build && ctest --verbose"]
