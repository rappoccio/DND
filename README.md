# DND Battle Map & Combat Simulator

A tactical D&D 5e (2024 rules / SRD 5.2) battle-map viewer and combat engine.
A C++ core handles all the rules — attacks, spells, conditions, movement,
line-of-sight, terrain and lighting — and a pygame GUI lets you place agents on
a map image and run encounters turn by turn.

## Architecture

- **C++ engine** (`gui/*.cpp`, `gui/*.hpp`) — the rules authority. Compiled
  with pybind11 into the `rpg_battle_map` Python module. Combat, spells,
  conditions, visibility, terrain and factions all live here.
- **Python GUI** (`gui/main.py` + `gui/*.py`) — map rendering, agent
  placement/config dialogs, and turn driving. Serializes encounters to JSON.
- **Tools** (`tools/`) — data pipelines: monster parsing, D&D Beyond character
  import, dungeon/encounter generation, breath-weapon derivation.
- **Data** — `maps/` (map images), `sprites/`, `encounters/` (saved scenes),
  and the JSON stat blocks / spell lists the engine loads.

Everything runs inside a Docker image (`rpg_map`) that bundles the toolchain and
a virtual display served to your browser over noVNC.

## Build

Builds the C++ extension into `gui/`:

```bash
./build.sh
```

Under the hood this is `cmake -S ./gui -B build -G Ninja` +
`cmake --build build` + `cmake --install build`, run inside the container
(`compile.sh`).

## Run

```bash
./run.sh maps/TestDNDMap.png
```

Then open **http://localhost:6080/vnc.html** in your browser. The left panel is
the battle map; the right panel configures and places agents.

## Test

The suite lives in `gui/test_*.py` (run via `run_all_tests.py`):

```bash
./test.sh
```

## Features

- Full 2024 class/subclass features across every class, plus feats, weapon
  masteries, and reactions (opportunity attacks, Shield, Counterspell, etc.).
- Data-driven monsters from JSON stat blocks with multiattack, recharge and
  legendary/breath actions; NPCs can be auto-driven in combat.
- Terrain, lighting/darkness, obscurement, factions, summoning, and
  concentration handled by the engine.
- Encounter and dungeon generators; D&D Beyond character import.

## License

Includes material from the System Reference Document 5.2 by Wizards of the Coast
LLC, licensed under CC BY 4.0. See [LICENSE](LICENSE).
