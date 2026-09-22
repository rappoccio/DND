# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ RUNNING COMMANDS — build and test are allowed; the rest is not

**Updated 2026-09-21 (user: "You're allowed to build and test now").** This replaces the
earlier blanket ban on running anything. The ban existed because the repo used to live in
an iCloud-synced directory where `build/` artifacts corrupted the cache; the repo moved to
`~/Claude/DND`, outside iCloud, and the root cause is gone.

**Allowed without asking, when you are running as Opus:**
- Building the extension: `./build.sh`, or the `cmake` sequence inside the `rpg_map` image.
- Running tests: `./test.sh`, `python3 tests/run_all_tests.py`, or a single suite.
- Read-only inspection: `git status` / `git log` / `git diff`, `ls`, `grep`, `cat`.
- Headless GUI checks through `tests/gui_driver.py` (synthesized pygame events, saved PNGs).

**Model-gated, and the user enforces it by switching models rather than by overriding it:**
- **Opus MAY build and run the suite.**
- **Sonnet and Haiku MUST NOT build or run tests, ever.** Hand the exact `docker run` line
  back to the user instead, and say plainly why.

**Still requires an explicit request, every time:**
- `git commit` — the user asks for it, or it does not happen.
- `git push` — a separate ask from committing. Refactor commits sit unpushed on `main` on
  purpose. Never push unasked.
- Launching the GUI for real (`./run.sh`, anything that publishes port 6080).
- Anything that writes outside the repo, or installs anything.

**Never, with or without a request:**
- `rm -rf` on any directory, `build/` above all. If something must be deleted, say which
  file and why, and let the user run it.
- `git add -A` / `git add .` — this tree carries a lot of untracked scratch (encounters,
  `.DS_Store`, loose `.md` files, `replay_log.txt`). **Stage files by name.**
- Staging `build/` or `replay_log.txt`.

**How to build (Docker; there is no native cmake/ninja on the macOS host, and the `.so` is
a Linux/py3.12 build):**
```bash
./test.sh                      # configure + build + install + run the whole suite
./build.sh                     # build only
# one suite, incremental (the image ENTRYPOINT is /bin/bash — pass -c, never "bash -c"):
docker run --rm -v "$HOME":/home/user rpg_map \
  -c "cd /home/user/Claude/DND && python3 tests/test_prompts.py"
```

Pure `main.py` edits need no rebuild — only C++ / binding changes do.

This section survives context compaction because it is in CLAUDE.md.

## Architecture Overview

This is a D&D 5e battle map viewer with a **two-layer architecture**:

1. **C++ core** (`battle_map.cpp/hpp`, `combat.hpp` + the `combat_*.cpp` translation units, `class_resources.cpp`, `agent.hpp`, `weapon.hpp`) — compiled as a pybind11 Python extension module (`rpg_battle_map.so`). Handles map image analysis, grid/wall detection, agent placement, movement, line-of-sight, and the full D&D 5e combat engine. No rendering dependencies; safe for headless RL training.

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
