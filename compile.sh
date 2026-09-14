#!/usr/bin/env bash
# Configure, build, and install the rpg_battle_map pybind11 extension.
#
# This is meant to run inside the project's Docker container (see gui/CLAUDE.md's
# Docker section) — that's where ninja is installed and where the built .so is
# actually used. It also works standalone on a host machine without ninja (e.g. this
# repo's macOS host, which only has `make` via Xcode CLT): the generator is picked
# based on what's actually on PATH instead of being hard-coded, so the same script
# works in both places without editing.
set -euo pipefail
cd "$(dirname "$0")"

BUILD_DIR=build
if command -v ninja >/dev/null 2>&1; then
  GENERATOR="Ninja"
else
  GENERATOR="Unix Makefiles"
fi

# A build/ directory configured with a different generator than the one we're about
# to use can't be reconfigured in place — CMake just errors out. Wipe it once instead
# of requiring a manual `rm -rf build`.
if [ -f "$BUILD_DIR/CMakeCache.txt" ]; then
  cached_generator=$(grep -m1 '^CMAKE_GENERATOR:INTERNAL=' "$BUILD_DIR/CMakeCache.txt" | cut -d= -f2)
  if [ -n "$cached_generator" ] && [ "$cached_generator" != "$GENERATOR" ]; then
    echo "compile.sh: build/ was configured with '$cached_generator', switching to '$GENERATOR' — removing stale build dir"
    rm -rf "$BUILD_DIR"
  fi
fi

cmake -S ./gui -B "$BUILD_DIR" -G "$GENERATOR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel
cmake --install "$BUILD_DIR"
