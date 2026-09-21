# Doors: Lockable / Unlockable — Implementation Plan

Doors that can be locked and unlocked. The **Knock** spell opens/unlocks doors;
**Sleight of Hand** checks pick locks. Status checkboxes are updated as work lands.

## Core design decision: a door is a **cell**, not an edge

Runtime blocking in this engine is entirely **cell-based**:
- Movement: `isBlocked()` (`battle_map.cpp:300`) and `floodFillPassable()` → `disallowed_`.
- LOS: `hasLineOfSight()`'s `wallCell()` lambda (`battle_map.cpp:968-978`) — blocks on
  `disallowed_` *or* `TerrainType::Wall`.
- Edge walls (`walls_`, `Wall{a,b}`) are only used at *detection time* to compute
  `disallowed_`; they are **not** consulted on the runtime hot paths.

Therefore a door occupies a doorway **cell** and expresses its blocking through the
existing terrain machinery:
- **Open** → cell is `TerrainType::Standard` (passable + transparent). Zero hot-path changes.
- **Closed / locked** → cell is `TerrainType::Wall` (reuses all existing movement + LOS blocking).

A `Door` struct is the source of truth for *state*; a single `syncDoorTerrain()` keeps the
cell's `TerrainType` in agreement. `isBlocked` and `hasLineOfSight` need **no changes**.

Relevant facts:
- `setTerrainType` / `get_terrain_type` already exist and are bound.
- Knock already exists in `spells.json` (type `Harm`, currently a no-op — no door concept).
- No skill-check system yet: `Stats` has only `stealth_prof`/`perception_prof` (`agent.hpp:106`).
  `CombatEngine.roll(sides, modifier)` exists (seeded RNG, `rpg_bindings.cpp:2052`).

---

## Phase 1 — C++ door foundation (`battle_map.hpp/.cpp` + bindings) ✅ DONE

- [x] Add `struct Door { int id; Cell cell; bool open=false; bool locked=false; int lock_dc=15; bool arcane_lock=false; int arcane_suppressed_turns=0; };`
- [x] `std::vector<Door> doors_` member + `doors()`, `doorAt(Cell)→int`, `addDoor(...)`, `removeDoor(id)`
- [x] `syncDoorTerrain(idx)`: open → `setTerrainType(Standard)` + erase cell from `disallowed_`; closed → `setTerrainType(Wall)`
- [x] `openDoor(id)` / `closeDoor(id)` / `lockDoor(id,dc)` / `unlockDoor(id)`; `openDoor` fails (returns false) on a locked/arcane-locked door
- [x] Bind all door API in `rpg_bindings.cpp` (`add_door`, `door_at`, `open_door`, `close_door`, `lock_door`, `unlock_door`, `remove_door`, `doors` property; `Door` class)
- [x] Build — green
- [x] Note: `addDoor` is idempotent per cell (replaces an existing door rather than stacking) so the Phase-4 load path can re-apply saved doors safely

## Phase 2 — Knock spell (data-driven) ✅ DONE

- [x] Add `bool opens_doors{false}` to `Spell` (`spell.hpp`) — detect Knock by flag, not name
- [x] In `executeSpell` (`combat_spells.cpp`): if `sp.opens_doors` and `doorAt(target_cell) >= 0` → unlock; if `arcane_lock`, set `arcane_suppressed_turns`; then `openDoor`; log it. Implemented via new `BattleMap::knockDoor(id, suppress_turns=100)` (encapsulates unlock + arcane-suppress + open + `syncDoorTerrain`); target cell = `action.aoe_col/aoe_row`
- [x] Set `"opens_doors": true` on Knock in `spells.json`
- [x] Round-trip `opens_doors`: bound on `Spell` in `rpg_bindings.cpp`; `_spell_to_dict` + `_dict_to_spell` in helpers.py; `_spell_to_dict` in main.py (dict→spell is helpers-only)
- [x] `knock_door` bound in `rpg_bindings.cpp`
- [x] Build — clean

## Phase 3 — Sleight of Hand + pick-lock action (`agent.hpp` + engine) ✅ DONE

- [x] Add `bool sleight_of_hand_prof{false}` + `bool sleight_of_hand_expertise{false}` to `Stats`, mirroring `stealth_prof`
- [x] Computed `sleightOfHand()` = `_mod(dex) + (prof ? prof_bonus : 0)` (+ prof_bonus again with expertise)
- [x] Round-trip the flags in BOTH `agent_loader.dict_to_stats` AND main.py save block (stats serializer round-trip rule); StatsDialog feeds `sleight_of_hand_prof` through `prof_flags` → main.py callback
- [x] StatsDialog checkbox for Sleight of Hand proficiency (right edge of the SAVE PROF. label row in `dialogs.py`)
- [x] `CombatEngine::attemptPickLock(bm, agent_idx, door_id) → PickLockResult{valid, success, roll, total, dc, log_message}` (`combat_riders.cpp`): `roll(20)+sleightOfHand` vs `lock_dc`; on success `unlockDoor`. Refuses an Arcane Lock; no-op on an already-unlocked door. `door_id` is `Door::id`.
- [x] Bind `attempt_pick_lock` + `PickLockResult` + the Stats flags/`sleight_of_hand()` in `rpg_bindings.cpp`
- [x] `test_doors.py` covers the skill bonus, door↔terrain, and all pick-lock paths
- [x] Build + test

## Phase 4 — GUI (placement, persistence, interaction, rendering)

Pure-Python phase: all bindings already existed (Phase 1–3), so **no C++ rebuild** is needed.

- [x] Terrain editor: add "Door" type ([5]) — single-cell click toggles a door; lock settings set via keyboard ([L] locked, [A] arcane, [+/-] DC) shown in the editor HUD. `bm.doors` is the source of truth; editor mutates `bm` directly (`terrain_dialogs.py`)
- [x] Persistence: new `"doors"` array in `*_terrain.json` ({cell, open, locked, lock_dc, arcane_lock}); `_save_terrain` serializes `bm.doors`; `_load_terrain` clears old doors then re-applies via `add_door` AFTER wall detect (closed-door Wall terrain must survive clear/detect)
- [x] Interaction: clicking an empty door cell → `_show_door_menu`: Open/Close (object interaction) + Pick Lock (action → `attempt_pick_lock`, sets `action_used`). Combat requires the acting creature adjacent; pre-combat the DM acts freely. Knock routes through the cell-cast path (`_pending_spell_opens_doors`); Arcane Lock blocks pick + shows a hint. Results to the combat log
- [x] Render: shared `draw_door_glyph` (wood slab / ajar frame + gold/purple padlock) drawn from `bm.doors` in `_draw_doors` (main render) and the terrain editor; always visible
- [x] GUI verification with the user

## Phase 5 — Wide (multi-cell) doors ✅ DONE

A door may now span **1–4 contiguous cells** as a single logical object (double doors,
gates, portcullises). The whole door opens / closes / locks / picks as a unit.

- [x] `Door::cell` → `std::vector<Cell> cells` (source of truth) + `anchor()` (first cell);
      `doorAt`, `syncDoorTerrain`, `addDoor`, `removeDoor`, `lockDoor` all iterate the cells
- [x] `addDoor(std::vector<Cell>, …)` multi-cell form (replaces any overlapping door, no
      stacking) + single-`Cell` convenience overload delegating to it
- [x] Bindings: `Door.cells` (read/write) + `Door.cell` (read-only anchor, back-compat);
      `add_door` bound for both a cell list and a single cell
- [x] Persistence: `*_terrain.json` doors store a `cells` array (legacy single-`cell` still
      loads); `_save_terrain`/`_load_terrain` round-trip the full span
- [x] Render: `_draw_doors` draws a slab per cell, padlock once on the anchor
      (`draw_door_glyph(..., draw_lock=)`)
- [x] Editor: **drag** to size a door (dominant axis, clamped to 4); a click on one cell
      still toggles. Live span preview + updated HUD hint
- [x] Interaction: a wide door is reachable when adjacent to **any** of its cells
- [x] `test_doors.py` covers span/terrain, removal, and overlap-replacement
- [x] Build + GUI verification with the user

## Phase 6 — Force / break-down (Strength check) ✅ DONE

A door can be **forced off its frame** with a Strength (Athletics) check. Mirrors the
Phase-3 pick-lock plumbing (skill bonus → engine check → result struct → GUI action),
but keyed on STR and available even against a locked or arcane-locked door — you are
smashing the door, not defeating the magic.

- [x] `Door::break_dc` (STR/Athletics DC, default 15) + `Door::broken` (smashed off its
      frame: permanently open, can't be closed or re-locked). `closeDoor`/`lockDoor` no-op
      on a broken door
- [x] `BattleMap::breakDoor(id)`: unlock + clear any Arcane Lock + mark broken + open +
      `syncDoorTerrain`. `addDoor(..., break_dc=15)` gained the extra parameter (both overloads)
- [x] `Stats::athletics_prof`/`athletics_expertise` + computed `athletics()` = STR mod
      (+ prof, + prof again with expertise), mirroring `sleightOfHand`
- [x] `CombatEngine::attemptBreakDoor(bm, agent_idx, door_id) → BreakDoorResult`
      (`combat_riders.cpp`): `roll(20)+athletics()` vs `break_dc` (+10 while an Arcane Lock
      is active); on success `breakDoor`. No-op on an already-open/broken door
- [x] Bindings: `Door.break_dc`/`Door.broken`, `break_door`, `attempt_break_door`,
      `BreakDoorResult`, the Stats flags + `athletics()`; `add_door` gained `break_dc`
- [x] Round-trips: Stats flags in `agent_loader.dict_to_stats` + main.py save block +
      StatsDialog (Athletics checkbox, `prof_flags`); door `break_dc`/`broken` in
      `*_terrain.json` (`_save_terrain`/`_load_terrain`; broken re-applied via `break_door`)
- [x] GUI: `_show_door_menu` "Break Down (DC N)" action on any closed door (shows +10 for
      an active Arcane Lock) → `_door_break_down` (spends the action). Terrain editor
      `[` / `]` set the placed door's break DC; broken doors render as a splintered frame
- [x] `test_doors.py` covers the Athletics bonus, success/failure, the Arcane Lock +10,
      broken-door immutability, and the open-door no-op

## Deferred (out of scope unless requested)

- [ ] Trap-on-lock
