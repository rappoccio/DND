# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ CRITICAL CONSTRAINT: NEVER RUN COMMANDS WITHOUT EXPLICIT PERMISSION

**YOU MUST NOT EXECUTE ANY BASH COMMANDS, PYTHON SCRIPTS, BUILD COMMANDS, OR ANY OTHER OPERATIONS WITHOUT THE USER EXPLICITLY REQUESTING IT.**

This includes:
- `cmake` build commands
- `python` script execution  
- `python3 tests/run_all_tests.py` or any test runners
- `rm`, `rm -rf`, or any destructive file operations
- `git` commands that modify state
- Anything that runs code or changes the filesystem

**Why:** The user handles all builds and executions. Running commands without permission has caused git lock issues in the build cache and violated explicit trust.

**What you CAN do:**
- Read files using Read tool
- Propose changes with Edit/Write tools
- Suggest commands for the user to run (via ! prefix in the prompt)

**What you MUST NOT do:**
- Execute anything via Bash tool without explicit "run X" request
- Suggest rm -rf or destructive operations on any directory, especially build/
- Assume context compaction won't make you forget this

This rule survives context compaction because it's in CLAUDE.md.

## Architecture Overview

This is a D&D 5e battle map viewer with a **two-layer architecture**:

1. **C++ core** (`battle_map.cpp/hpp`, `combat.cpp/hpp`, `agent.hpp`, `weapon.hpp`) — compiled as a pybind11 Python extension module (`rpg_battle_map.so`). Handles map image analysis, grid/wall detection, agent placement, movement, line-of-sight, and the full D&D 5e combat engine. No rendering dependencies; safe for headless RL training.

2. **Python GUI** (`main.py`) — pygame-based renderer that imports the C++ extension as `import rpg_battle_map as rpg`. Draws the map, grid overlay, agents, and the right-side configuration panel. All user interaction (placing agents, configuring stats/weapons, running combat) lives here.

The pybind11 bindings are defined entirely in `rpg_bindings.cpp` — the canonical reference for the Python-facing API surface (snake_case names differ from C++ camelCase).

## Build

```bash
# Configure and build the pybind11 extension (fetches pybind11 v2.13.1 automatically)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel

# Install the .so next to main.py so Python can import it
cmake --install build
```

Requires: CMake ≥ 3.25, C++23 compiler, OpenCV 4.x, Python 3 with dev headers.

## Run

```bash
# After building and installing:
python main.py <map_image.png>
```

## Docker (display via browser — no XQuartz needed)

```bash
docker build -t rpg_map .
docker run --rm -p 6080:6080 -v ~/my_maps:/app/maps rpg_map /app/maps/mymap.png
# Open http://localhost:6080/vnc.html in any browser
```

The container uses Xvfb + x11vnc + noVNC to avoid the XQuartz GLX crash on macOS.

## Tests

The Python unit suite lives in the top-level `tests/` directory (`tests/test_*.py`),
driven by `tests/run_all_tests.py`. Tests import the compiled `rpg_battle_map`
module and read data JSONs (`spells.json`, `DND2024_MonsterStats.json`, …) from
this `gui/` directory: each test prepends `gui/` to `sys.path`, and the runner
executes every suite with its working directory set to `gui/` so the engine's
cwd-relative JSON loads resolve. New tests go in `tests/` and must be registered
in `tests/run_all_tests.py`. Test fixtures (e.g. `*.golden.txt`) live in `tests/`
alongside their test; shared data JSONs stay in `gui/`. `test_helpers.py` provides
the common setup helpers.

## Key Design Decisions

- **OpenCV stays out of headers**: `battle_map.hpp` includes no OpenCV headers; `cv::Mat` usage is confined to static free functions in `battle_map.cpp`. This keeps the pybind11 compilation boundary clean.

- **Agent is abstract**: `Agent` (`agent.hpp`) is a non-copyable abstract base. `BattleMap` internally creates `ConfiguredAgent` instances (from `configured_agent.hpp`) when `applyAgentConfigs()` is called. The four pure virtuals (`action`, `bonusAction`, `walk`, `fly`, `reaction`) are wired to no-ops in `ConfiguredAgent`.

- **C++ uses camelCase; Python bindings use snake_case**: e.g., `analyzeGrid()` → `analyze_grid()`, `cellPixelSize` → `cell_pixel_size`. See `rpg_bindings.cpp` for the full mapping.

- **CombatEngine is RL-ready**: `getBattleObservation()` returns a fixed-length float vector (12 + max_targets×14 floats) for NN input; `availableAttacks()` returns the discrete action space. Pass a fixed seed to `CombatEngine(seed)` for deterministic rollouts.

- **Wall detection uses two methods**: primary is dark-cell threshold (cells with mean grayscale < `darkCellThreshold` are obstacles); secondary is edge-based detection for maps that draw walls as lines between cells. Both are tunable via `BattleMap.params` (`DetectionParams`).

- **Movement**: Walk uses Dijkstra BFS through passable cells; Fly uses Chebyshev radius ignoring terrain. The `CombatEngine` tracks per-turn movement budgets (`beginTurn`, `spendWalk`, `spendFly`, `getWalkRemaining`).

## C++ Standards

C++23 with `-Wall -Wextra -Wpedantic -Wshadow -Wconversion`. Integer ability score is named `intel` (not `int`) to avoid the C++ keyword conflict.
