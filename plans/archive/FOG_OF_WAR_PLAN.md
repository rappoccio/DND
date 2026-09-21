# Fog of War — Implementation Plan

Status: **DRAFT / awaiting clearance**  ·  Date: 2026-07-09

## Goal

Render cells the player party has never seen as a **dark opaque grey** ("fog"),
accounting for lighting, vision senses, walls, and doors. Fog is **cleared once
and stays cleared** — the party "has a map," so a cell that has ever been seen
is permanently revealed (no re-fogging when they leave or the lights go out).

## Locked design decisions

| Question | Decision |
|---|---|
| What does fog hide? | **Terrain + enemies.** Grey out never-explored terrain cells, AND suppress enemy tokens whose footprint sits entirely in never-explored cells. |
| Whose vision clears fog? | **Whole PC party** (`PC_FACTION = 2`). A cell is cleared if *any* living party member has ever seen it. |
| Persistence | **Engine + terrain JSON.** Explored mask lives in C++ `BattleMap`, serialized into `*_terrain.json`, survives save/reload. |
| Re-fogging | **None.** Monotonic explored set — cells only ever go unexplored → explored. |
| Blindsight | **Known limitation** (see below) — not wired into cell vision today. |

## What already exists (reuse, don't rebuild)

- **Per-cell vision:** `BattleMap::canSee(obs_origin, obs_size, dv_ft, ts_ft, ds_ft, tgt, tgt_size)`
  — already bound to Python as `can_see`. Called with a 1×1 target `cell` it answers
  "can this observer see this cell," honoring:
  - **LOS** via `hasLineOfSight` (Bresenham through `terrainType_ == Wall` + `disallowed_`).
  - **Doors** — a closed door syncs its cell to `TerrainType::Wall` (`syncDoorTerrain`), so
    LOS is gated by open/closed state automatically. Nothing extra to do for doors.
  - **Lighting** via `getLightLevel` (`lightLevel_` layer from `updateLighting`): Dark needs
    darkvision, MagicalDark needs devil's sight, HeavilyObscured (fog/smoke) blocks all but
    truesight/blindsight, Dim/LightlyObscured visible with disadvantage, Clear/Sunlight visible.
  - **Senses:** darkvision / truesight / devil's sight ranges.
- **Lighting layer:** `updateLighting()` recomputes `lightLevel_` from base + `activeLightEffects_`
  (torches, Darkness, Daylight, fog). Already called on every light change.
- **Overlay-render pattern:** `_draw_lighting_overlay()` in `main.py` is the exact per-cell
  overlay pattern to mirror for the fog overlay (per-cell alpha rect, pan-aware blit).
- **Serialization hooks:** `_save_terrain` (main.py ~11107) / `_load_terrain` (~11030) already
  round-trip `walls_enabled` + `doors`; add `explored` alongside.

## Design

### 1. C++ `BattleMap`: persistent explored mask (PC-party scoped)

- New member: `std::vector<uint8_t> explored_;` sized `cols_ * rows_`, flat index `row*cols_+col`,
  reset to 0 on grid (re-)analysis. (Single mask, PC-party only — matches the single-party model.
  If multi-faction fog is ever needed, promote to `std::unordered_map<int, std::vector<uint8_t>>`.)
- **Reveal (monotonic OR):**
  ```
  void BattleMap::revealFogForFaction(int faction) noexcept;
  ```
  For each **living** placed agent on `faction`, read its `Agent::Stats` directly
  (`darkvision_range`, `truesight_range`, `devilssight_range`, size, and a base perception
  range = `max(20, (wis/2)*5)` ft like `computeVisibility`). For every cell within the max of
  those ranges, if `canSee(agent.origin, size, dv, ts, ds, cell, 1)` → `explored_[idx] = 1`.
  Never clears a bit. (Reading full stats here is deliberate — it's where blindsight would fold
  in later without touching `canSee`'s signature.)
- **Queries / manual control:**
  ```
  bool isExplored(Cell c) const noexcept;
  const std::vector<uint8_t>& exploredMask() const noexcept;
  std::vector<Cell> exploredCells() const;         // for JSON export
  void setExplored(Cell c, bool v) noexcept;       // DM paint
  void setExploredCells(const std::vector<Cell>&); // JSON import (replaces mask)
  void revealAllFog() noexcept;                    // DM "reveal all"
  void clearFog() noexcept;                         // DM "reset fog"
  ```

### 2. Reveal triggers

Call `revealFogForFaction(PC_FACTION)` (via a thin GUI `self._refresh_fog()` guarded by a dirty
flag) after any event that can change party vision:
- agent moved / placed / removed,
- door opened or closed,
- light effect placed / removed / ticked (`tick_light_effects`, `update_lighting`),
- turn advanced / combat begun,
- terrain (re)loaded.

Because reveal is a monotonic OR, an occasional redundant recompute is harmless; the dirty flag
just avoids doing it every frame.

### 3. Python bindings (`rpg_bindings.cpp`)

Expose: `reveal_fog_for_faction`, `is_explored`, `explored_cells`, `set_explored`,
`set_explored_cells`, `reveal_all_fog`, `clear_fog`.

### 4. GUI rendering (`main.py`)

- **`self.show_fog` toggle** + a `btn_toggle_fog` button ("Fog: ON/OFF") mirroring the Lighting
  button; default **ON** in a play scene. Right-click / menu entries: "Reveal all fog", "Reset fog".
- **`_draw_fog_overlay()`** (mirror of `_draw_lighting_overlay`): for every cell with
  `not bm.is_explored(cell)`, fill a **dark opaque grey** rect — `(24, 24, 28, 245)` — on a
  SRCALPHA surface, blit pan-aware over the map. Drawn as the topmost *terrain* layer (after the
  static overlay + lighting overlay), so it also hides beneath-agent overlays (spell/terrain
  effects) in unexplored areas.
- **Enemy hiding** in `_draw_agents`: before drawing a non-party agent, skip it if **every** cell
  of its footprint is unexplored (`all(not bm.is_explored(c) for c in footprint)`). PCs/allies
  (same non-zero faction as the party) are always drawn. This keeps the "hide enemies" behavior
  keyed to the same explored set, so it can never draw a token on top of fog.
- **Draw order:** map → static overlay → lighting overlay → **fog overlay** → agents (party always;
  enemies gated) → selection/UI. When `show_fog` is off, skip the overlay and the enemy gate.

### 5. Serialization

- `_save_terrain`: add `data["explored"] = [[c.col, c.row] for c in bm.explored_cells()]`
  (or a flat-index list; keep it compact). 
- `_load_terrain`: `bm.set_explored_cells([...])` after grid analysis; default empty (all fogged)
  when the key is absent, so old saves start fully fogged.
- Follows the same round-trip discipline as the walls/doors block — added to **both** save and load.

## Known limitations (explicit)

1. **Blindsight is not modeled for fog / cell vision.** `blindsight_range` exists on `Agent::Stats`
   but is used only by `piercesInvisibility` (invisibility) in `combat_visibility.cpp`; it is *not*
   read by `canSee`/`getLightLevel`. Consequently a blindsighted creature (and the 10 ft blindsight
   from the **Blind Fighting** style / **Skulker** feat) will **not** reveal fog through blindsight —
   only darkvision / truesight / devil's sight / normal light do. Fix later by having
   `revealFogForFaction` also mark cells within `blindsight_range` that pass LOS (regardless of
   light), since it already reads full stats.
2. **Single-party vantage.** Fog is computed for `PC_FACTION` only; no per-faction / per-side fog.
3. **No re-fogging (by design).** A room seen once stays revealed even after the party leaves or the
   light dies. Enemies that later enter an *explored* room are shown by this fog gate even if the
   party couldn't currently see them in the dark — dynamic per-observer enemy concealment stays with
   the existing agent-visibility system (`computeVisibility`/`hidden`/`invisible`), not this layer.
4. **Enemy-token hiding keys off the explored terrain set, not live LOS.** Targeting/attack
   legality is still governed by the engine's live visibility; this layer only decides whether the
   sprite is drawn.

## Testing (`gui/test_fog_of_war.py`)

- Wall between PC and a far cell → far cell stays unexplored; open a door in the wall → it clears.
- Darkvision PC reveals `Dark` cells in range; a `MagicalDark` cell stays fogged without devil's sight;
  devil's-sight PC clears it.
- `HeavilyObscured` (fog) cell stays unexplored for a plain PC.
- Enemy standing in an unexplored cell is not returned as drawable; becomes drawable after reveal.
- Save → load round-trips the explored mask (persisted); absent key → fully fogged.

## Touch list

- `gui/battle_map.hpp` / `battle_map.cpp` — `explored_`, reveal/query/paint methods, reset on analyze.
- `gui/rpg_bindings.cpp` — bindings.
- `gui/main.py` — `show_fog`, `_draw_fog_overlay`, `_draw_agents` enemy gate, `_refresh_fog` triggers,
  toggle button + reveal/reset menu, `_save_terrain`/`_load_terrain` explored round-trip.
- `gui/test_fog_of_war.py` — new tests.
- **Build required** (user builds); **user runs tests**.
