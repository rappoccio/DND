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
- Multi-map dungeons: several map images on one floor plus stacked floors,
  joined by ladders and doorways (see below).

## Multi-Map Dungeons (floors & pages)

A dungeon is several map PNGs ("pages") placed on one shared global `(X, Y, Z)`
grid: `Z` is the floor, `(X, Y)` a cell on that floor. Each page keeps its own
encounter sidecars (`*_agents.json`, `*_terrain.json`, …); a `<name>.dungeon.json`
manifest records where each page sits on the grid and which one is the entry.
Opening an encounter whose folder holds a matching `.dungeon.json` enters dungeon
mode automatically.

**Build one by hand** (right panel → **Dungeon…**):

1. **New Dungeon (this map)** — makes the current map + encounter page 1 at
   origin `(0, 0, 0)` and writes the manifest. (The map needs a grid — use
   **Set Grid…** first if it has none.)
2. **Add Page…** — pick another PNG. It is placed east of the floor's rightmost
   page with a fresh empty encounter, and becomes the active page.
3. **Pages / Overview…** — the floor map and page list. Select a page (in the
   list or on the map) to set its global **origin** (X/Y/Z), make it the entry
   page (★), jump to it, or remove it. Pages that abut on the grid become each
   other's West/North/South/East neighbours.
4. **Save Dungeon** — writes the manifest plus the active page's scene.

**Generate one**: *Generate Dungeon* with **Floors > 1** (and/or *Each floor
N×M*) carves every floor/tile, populates it, links the floors with **ladders** and
the abutting maps on each floor with **linked doors** (one per shared edge,
tunnelled to the nearest room on both sides), and writes the manifest for you.

**Moving around:** the panel's Floor-nav block pages between abutting maps
(West/North/South/East) and changes floors (Floor ±). In play, a creature uses a
**ladder** (terrain editor type **[6]**) to change floor, or an **open door
linked to a neighbouring map** (terrain editor **[K]**) to cross to it; both are
explicit actions on the creature's menu, and both carry that creature to the
target page.

### Known limitations

- **One page is simulated at a time.** A ladder or linked door is a discrete
  transition: the current scene is saved, the target page is loaded, and the
  crossing creature is placed on it. Monsters on other pages are frozen on disk.
- **No cross-boundary combat or pursuit** — you cannot see, move, or attack
  across a portal, and initiative does not follow you to another page.
- **Portals are out-of-combat only** (as is paging/changing floors); crossing
  during a fight is refused until cross-page combat exists.
- **Pages must share a cell size** for their global coordinates to line up; use
  **Set Grid…** on each page.
- Only the acting creature crosses a portal — the rest of the party does not
  follow automatically.

## License

Includes material from the System Reference Document 5.2 by Wizards of the Coast
LLC, licensed under CC BY 4.0. See [LICENSE](LICENSE).
