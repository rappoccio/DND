# ─────────────────────────────────────────────────────────────────────────────
#  RPG Battle Map – Docker build  (C++ core + Python/pygame GUI)
#
#  Display strategy: Xvfb (virtual framebuffer) inside the container + VNC.
#  SDL2 renders to the internal Xvfb display (:99) so it never touches
#  XQuartz's GLX, avoiding the BadValue/GLXCreateContext crash entirely.
#  x11vnc forwards the Xvfb framebuffer over VNC on port 5900.
#
#  Build:
#    docker build -t rpg_map .
#
#  Run:
#    docker run --rm -p 6080:6080 \
#      -v ~/my_maps:/app/maps \
#      rpg_map /app/maps/mymap.png
#
#  View (any browser, no software needed):
#    http://localhost:6080/vnc.html
# ─────────────────────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 1 – Builder: compile the pybind11 extension
# ══════════════════════════════════════════════════════════════════════════════
FROM python:3.12-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY agent.hpp            ./
COPY configured_agent.hpp ./
COPY weapon.hpp           ./
COPY spell.hpp            ./
COPY combat.hpp           ./
COPY combat.cpp           ./
COPY battle_map.hpp       ./
COPY battle_map.cpp       ./
COPY rpg_bindings.cpp     ./
COPY CMakeLists.txt       ./

RUN cmake -S . -B build \
        -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --parallel \
    && cmake --install build


# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 2 – Runtime
# ══════════════════════════════════════════════════════════════════════════════
FROM python:3.12-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV runtime (apt resolves the full transitive dep tree)
    libopencv-dev \
    # Virtual framebuffer X server
    xvfb \
    # VNC + noVNC (browser-based viewer, no VNC client needed)
    x11vnc \
    novnc \
    websockify \
    # X11 / Mesa (needed by SDL2 and Xvfb)
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
    # SDL2 runtime
    libsdl2-2.0-0 \
    libsdl2-image-2.0-0 \
    libsdl2-ttf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pygame

# Copy compiled C++ extension
COPY --from=builder /src/rpg_battle_map*.so /app/

# Copy Python files and startup script
COPY main.py        /app/
COPY read_stats_from_csv.py /app/
COPY entrypoint.sh  /app/
RUN chmod +x /app/entrypoint.sh

WORKDIR /app
VOLUME ["/app/maps"]

# Internal Xvfb display — no XQuartz involved
ENV DISPLAY=:99
ENV PYTHONPATH=/app
ENV SDL_AUDIODRIVER=dummy
ENV PYTHONUNBUFFERED=1

EXPOSE 5900 6080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["--help"]
