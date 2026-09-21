# Floors & Multi-Map Dungeons — Implementation Plan

Large dungeons that span **multiple maps on one floor** (page left/right/up/down over a
shared coordinate grid) and **multiple floors** stacked on the `z` axis, connected by
**ladders** (vertical portals) and **doors** (horizontal staples between adjacent maps).

Design goal (from *Extending Maps for Dungeons.md*): one **global `(x, y, z)` grid** so a
ladder is simply a portal `(x, y, z1) → (x, y, z2)`, and a door staples two same-`z` maps
by matching their global coordinates. All floors align to the same global origin, sized to
the largest floor.

Status checkboxes are updated as work lands, mirroring the door/fog plan style.

---

## Decisions locked with the user

- **One active map at a time; portals are discrete transitions.** The C++ engine simulates
  exactly one `BattleMap`. Crossing a ladder or an inter-map door **saves the current scene,
  switches the active map, and repositions the agent(s)** onto the target map. There is no
  seamless shared space across a boundary. → see **Known Limitations**.
- **Stapled maps are distinct areas joined by a doorway**, not one room split across two
  PNGs — so a transition (not seamless LOS/movement) is the correct model.
- **`z` goes into `Cell`** (per user), but scoped carefully — see Phase 1. The engine's
  active-map internals keep local cells at `z = 0`; `z` carries the **floor** at the global
  addressing layer. This honors the request without destabilizing the hot paths.
- **Scale:** up to ~3×3 pages per floor and 3–4 floors (~20 maps) for an *epic* dungeon;
  the common case is 1×1–2×2 pages and 1–2 floors. Design for ~20 maps, optimize for small.

---

## Current architecture (grounding facts)

- **The engine is single-map.** `self.bm` is one `rpg.BattleMap` built from one PNG passed
  on the CLI (`main.py:376`), loaded once in `__init__`. Combat, movement (BFS/flood-fill),
  LOS/visibility, occupancy, and fog all run inside that one map. **No runtime PNG swap
  exists yet.**
- **`Cell` is `(col, row)` only** (`cell.hpp`). Agents carry `(x, y, z)` but **`z` is dead** —
  it only appears in the Manhattan distance inside `Agent::_moveTo` (`agent.hpp:1141`).
  Nothing on cells/grid/terrain/doors is z-aware. `footprintDistance` (`cell.hpp:29`, the
  single-source reach/adjacency formula) is 2D.
- **An "encounter" is already decoupled from the PNG:** four sidecar JSONs
  (`_agents`, `_terrain`, `_effects`, `_lighting`) sharing a base name. `_set_encounter_base`
  (`main.py:1580`) re-points them; `_load_agents` / `_load_terrain` / `_load_lighting` /
  `_load_spell_effects` swap the whole scene **on the same image**. **This is the seam we
  reuse to swap floors** — we add "swap the PNG too."
- **Doors are the precedent for portals:** cell-based objects (1–4 cells) that flip terrain
  and round-trip through `_terrain.json` (`DOORS_IMPLEMENTATION_PLAN.md`). Ladders and
  inter-map doors follow the same cell-object + terrain-sidecar pattern.
- **Panning** (`pan_x`/`pan_y`) already scrolls the viewport over one image — reused for
  intra-map scrolling; **paging** (switching to a neighbor PNG) is the new concept.
- **Agents serialize `col`/`row` only** (`main.py:10716`); `AgentConfig` has `startCol/startRow`;
  `placed_agents[i].origin` is a `Cell`.

---

## Coordinate model

Two layers, kept deliberately distinct:

| Layer | Coordinate | Owner | Notes |
|-------|-----------|-------|-------|
| **Local** | `(col, row)` | a `BattleMap` (one page) | What every engine hot path uses today. Unchanged. `z` stays 0. |
| **Global** | `(X, Y, Z)` | the `Dungeon` manifest | `Z` = floor; `(X, Y)` = position on the shared floor grid. |

Each page has an **origin** `(origin_col, origin_row, z_level)` = the global coordinate of
its local `(0, 0)`. Conversion:

```
global = (origin_col + col, origin_row + row, z_level)
local  = (X - origin_col, Y - origin_row)   # valid only when Z == z_level and in-bounds
```

A **ladder** connects global `(X, Y, z1) → (X, Y, z2)` (same X,Y by construction when floors
share an origin). A **door staple** connects `(X, Y, z) → (X', Y', z)` across two same-`z`
pages whose footprints abut in the global grid.

---

## C++ vs Python split

- **C++ (minimal, Phase 1 only):** `z` field on `Cell`; global placement (`origin_col`,
  `origin_row`, `z_level`) + `local_to_global` / `global_to_local` on `BattleMap`; bindings.
  Everything else is Python.
- **Python (Phases 0, 2–6):** re-entrant map loading, the `Dungeon` manifest, active-map
  switching + paging UI, ladders, inter-map doors, persistence, overview map.

---

## Phase 0 — Make map loading re-entrant (Python) — prerequisite

Today the PNG, surface, scale, overlay, and `BattleMap` are all built inline in `__init__`
(`main.py:376–420`). Nothing can change the active image at runtime.

- [x] Extract that block into `self._load_map_png(path)` that (re)builds `self.bm`,
      `self.map_surf`, `self.map_scale`, `self.map_rect`, `self.overlay`, and re-runs
      `analyze_grid` / `detect_walls`. `__init__` calls it once.
- [x] Reset viewport state (`pan_x/pan_y`, selection, drag) on swap.
- [x] Sprite cache (`self.sprites`) survives a swap (keyed by path) — no change needed, verify.
      (`_load_map_png` never touches `self.sprites`; it's created once in `__init__`.)
- [ ] Manual test: call `_load_map_png` on a second PNG mid-session; confirm the scene
      rebuilds cleanly with no stale overlay/agents.

## Phase 1 — `z` in `Cell` + global placement on `BattleMap` (C++)

**`Cell` z (scoped):**
- [x] `struct Cell { int col{0}; int row{0}; int z{0}; };` — `operator==` stays defaulted
      (now z-sensitive). Update `CellHash` to fold in `z` (`cell.hpp`, folds `z << 8`).
- [x] **Hot paths stay 2D / z=0.** `footprintDistance` ignores `z` (reads only `.col`/`.row`;
      unchanged — see `[[footprint_distance_single_source]]`). Terrain flat indexing
      (`row*cols_+col`) is unchanged. All existing `rpg.Cell(col,row)` call sites keep `z=0`
      via the default; the 2-arg `Cell(int,int)` binding still exists. Audited: no structured
      bindings on `Cell` (only `.col`/`.row` fields touched by hot paths), engine live cells
      stay `z=0`; `z` is meaningful only on cells returned from `local_to_global`.
- [x] Round-trip doors' `z`: door cells stay `z=0` on the active page (2-arg `Cell` ctor
      defaults `z=0`), so existing door/terrain saves reload unchanged. (No z written to door
      JSON yet — dead weight while every live door is on a `z=0` page; revisit if doors ever
      address other floors.)

**`BattleMap` global placement:**
- [x] Members `origin_col_`, `origin_row_`, `z_level_` (all default 0) + getters/setters
      (`battle_map.hpp`).
- [x] `Cell localToGlobal(Cell) const` (returns a Cell with `z = z_level_`) and
      `std::optional<Cell> globalToLocal(int X, int Y, int Z) const` (nullopt if wrong
      floor or out of the page's `[0,cols)×[0,rows)`) — inline in `battle_map.hpp`.
- [x] Bind `origin_col` / `origin_row` / `z_level` / `local_to_global` / `global_to_local`
      + `Cell.z` (readwrite, 3-arg ctor, repr) in `rpg_bindings.cpp`.
- [x] Build — green. **User builds** per `[[feedback_user_runs_builds]]`; hand off.

*Note:* agents inherit their floor from the active map's `z_level_`; we do **not** need to
stamp `agent.z` for the MVP (floor is a map property). Optional: set `agent.z = z_level_` on
placement so an agent's global position is self-describing — cheap, deferrable.

## Phase 2 — `Dungeon` manifest model (Python)

The "keep track of multiple maps at a time" layer. New module `gui/dungeon.py`.

- [x] `MapPage` record: `id`, `png` (path), `encounter_base` (the `_agents.json` base),
      `origin` `[gx, gy, z]`, `cols`, `rows`. Plus `contains_global` / `global_to_local` /
      `local_to_global` footprint helpers (manifest-side mirror of the C++ conversion, so a
      neighbour page need not be loaded into the engine to resolve a portal target).
- [x] `Dungeon`: ordered `pages`, an `entry_page_id`, plus helpers:
      `page_at_global(X,Y,Z) -> MapPage|None`, `neighbor(page, dir) -> MapPage|None`
      (adjacency by origin arithmetic on the same `z`; `dir` ∈ left/right/up/down, largest-
      overlap wins), `floors() -> sorted set of z`. Also `page_by_id`, `entry_page`,
      `pages_on_floor`, and `add_page`/`remove_page` (keep `entry_page_id` valid).
- [x] Persist to `<name>.dungeon.json` (a **fifth** sidecar family, at the dungeon level, not
      per-encounter). `save`/`load` + `to_dict`/`from_dict` (repairs a dangling entry pointer);
      `dungeon_path_for(base)` derives the sibling manifest path. Portals live in the terrain
      sidecars (Phases 4–5), so the manifest stays about *placement*; it derives door-staple
      adjacency from origins.
- [x] `dungeon.json` schema documented at the top of `dungeon.py`.

## Phase 3 — Active-map switching + paging UI (Python)

- [x] `self.dungeon` (optional): when set, the app is in "dungeon mode." Plus
      `self.dungeon_page` (the loaded `MapPage`). Activated by
      `_load_dungeon_manifest_if_present()` — a sibling `<base>.dungeon.json` next to the
      startup encounter opens its entry page (deferred to the end of `__init__` so the
      combat engine / catalogs / panel `_switch_to_page` needs are ready). Explicit
      New/Open Dungeon GUI is Phase 6.
- [x] `self._switch_to_page(page, drop_cell=None, carry=None, force=False)`:
      1. `_save_agents` (excl. carried) / `_save_terrain` for the current page.
      2. `_load_map_png(page.png)`; `_apply_page_origin` sets `bm` origin/`z_level`.
         Relative manifest paths resolve against the map dir.
      3. `_set_encounter_base(page.encounter_base)`; `_load_terrain` / `_load_lighting` /
         `_load_spell_effects` / `_load_agents`.
      4. If `carry` (agents crossing a portal), inject via `_inject_carried_agents` onto
         the target at `drop_cell` — **incremental add, never `apply_agent_configs`**
         (`[[agent_dual_list_gotcha]]`). Carried agents are serialized losslessly through
         the canonical `_save_agents`/`_load_agents` (new `exclude_indices` param drops
         them from the source page); MVP drops their transient active-conditions.
- [x] **Paging controls:** on-map HUD (`_draw_dungeon_nav`) — West/North/South/East page
      to the adjacent same-`z` page (origin arithmetic, `Dungeon.neighbor`), greyed +
      inert when no neighbor. **Floor +/−** switcher changes `z` (`_floor_step`, lands on
      the page under the current top-left, else the first page on that floor).
- [x] **Floor overview:** built from manifest origins — landed in Phase 6 as the map inside
      the Pages / Overview dialog (`_draw_floor_overview`): one box per page on the floor,
      gold = the page loaded in the engine, ★ = entry page, clickable to select.
- [x] Guard: switching pages **out of combat** only for the MVP. In combat `_switch_to_page`
      refuses with a status flash (a full "leave combat?" prompt is deferred).
- [x] `test_floors.py`: dungeon-manifest logic the paging drives — global/local
      conversion, neighbour adjacency + largest-overlap tie-break, floor enumeration,
      `page_at_global`, entry-page repair, save/load round-trip. (Phases 4-5 extend it.)

## Phase 4 — Ladders (vertical portals) (Python, cell-object like doors)

- [x] `ladders` array in `_terrain.json`: `{ cells: [[c,r],…], target: [X,Y,Z] }`
      (target in **global** coords; usually `[gx+c, gy+r, z±1]` for aligned floors).
      `_normalize_ladders` coerces on load (`main.py`); `_ladders` is the app-side store.
- [x] Editor: place a ladder cell (type **[6]** in the terrain editor); target auto-fills
      to the same global `(X,Y)` on `z+1` (up) or `z-1` (down) — direction toggled with
      **[U]**; click an existing ladder to remove it. Derives the global target from the
      active map's `origin_col/origin_row/z_level` (Phase 1 fields), so no manifest access
      needed in the modal editor. (Free retarget UI deferred; toggle covers the common case.)
- [x] Render a ladder glyph (`draw_ladder_glyph` in `terrain_dialogs.py`, shared by the
      render loop's `_draw_ladders` and the editor; rails+rungs + up/down direction arrow).
- [x] Interaction/trigger: an explicit **"Use Ladder" action** (door-menu style, chosen over
      auto-on-step per the Open-items default) — `_show_ladder_menu` → `_use_ladder` resolves
      `target` → `dungeon.page_at_global(...)` → `page.global_to_local(...)` →
      `_switch_to_page(page, drop_cell, carry=[agent])`. Out-of-combat only (the switch's
      combat guard flashes otherwise); in-combat adjacency to the ladder is required.
- [x] Round-trip ladders in `_save_terrain` / `_load_terrain` (mirror the door array; cleared
      on scene swap, re-applied from JSON — Python-side, no wall-detect ordering concern).
- [x] `test_floors.py`: origin/global conversion + ladder resolves to the right page+cell
      (up, down, off-footprint→None) and a ladder JSON round-trip. **13/13 green.**
- [x] Build/test handoff: pure-Python change (no C++), floors tests pass locally; user runs
      the full suite per `[[feedback_user_runs_tests]]`.

## Phase 5 — Doors between maps (horizontal staple) (Python)

Extend the existing door with an optional cross-map target so a doorway on a page edge leads
to the abutting same-`z` page.

- [x] Add `link_target: [X,Y,Z] | null` to a door's terrain-JSON record (null = ordinary
      in-map door; unchanged behavior). Same-`z` by construction. Doors live in C++
      `bm.doors` and can't hold the field, so the link is a Python side-table
      (`self._door_links`) keyed by the door's cell footprint (`door_link_key`, stable
      across save/reload); serialized as each door record's `link_target`.
- [x] Placement: **[K]** in the terrain editor toggles "link to neighbor"; a door placed on
      a page edge auto-targets the matching global cell one step beyond that edge
      (`_door_link_target`, derived from the active map's origin/`z_level` — no manifest
      access needed, the target page resolves at use time). A wide door uses its middle
      cell as the crossing point. A teal chevron marks a linked door.
- [x] Interaction: **explicit "Go through door (to floor Z)"** door-menu action (matches the
      ladder's explicit-action MVP over auto-on-step) — appears only when the door is
      **open**, so a locked/arcane-locked (thus closed) staple blocks passage. Resolves
      `link_target` → `page_at_global` → `global_to_local` →
      `_switch_to_page(page, drop_cell, carry=[actor])`; out-of-combat only via the switch's
      combat guard.
- [x] Round-trip `link_target` in the door serializer (both directions —
      `[[stats_serializer_roundtrip]]` discipline): written in `_save_terrain`, rebuilt in
      `_load_terrain`; cleared on scene swap; editor read-back on ESC.
- [x] `test_floors.py`: a linked door resolves to the neighbor page's matching cell (right +
      left edge), an interior door has no target, and the `link_target` JSON round-trips.

## Phase 6 — Dungeon persistence & polish (Python)

- [x] GUI: a **"Dungeon…"** panel button opens a menu (`_show_dungeon_menu`) — **New Dungeon
      (this map)** (`_dungeon_new`: current PNG + encounter become page 1 at origin (0,0,0),
      manifest written at `dungeon_path_for(save_path)`), **Open Dungeon…** (`.dungeon.json`
      file browser → `_on_open_dungeon_chosen`, re-points `_map_dir` at the manifest's folder
      so relative page paths resolve, then loads the entry page), **Save Dungeon**
      (`_dungeon_save`: manifest + the active page's agents/terrain), **Add Page…**
      (`_on_add_page_png_chosen`: PNG → new page east of the floor's rightmost page with a
      fresh empty encounter; its `cols`/`rows` are recorded *after* the switch, since the
      footprint is only known once the grid is analyzed), **Close Dungeon**, and
      **Pages / Overview…**.
- [x] **Pages / Overview** modal (`_modal_dungeon_pages`): page list (★ entry, ● loaded) +
      the floor map (`_draw_floor_overview`, clickable) + X/Y/Z **origin steppers** that place
      the selected page on the global grid, with Set Entry / Go To Page / Remove. Edits apply
      to the manifest in memory; `_dungeon_pages_overview` persists them on close, re-stamps
      the engine origin if the active page moved, and switches pages on a Go To (a switch
      resizes the window, so it must happen outside the modal's draw loop).
- [ ] Optional: when generating a dungeon (`_on_generate_dungeon`) across multiple pages,
      order rooms across pages by walk distance in the global grid (later; single-page today).
      *(still deferred — out of Phase 6 scope)*
- [x] `README.md` — new **Multi-Map Dungeons (floors & pages)** section: the manifest/global-grid
      model, the hand-authoring workflow (New → Add Page → Overview → Save), the generator path,
      and how ladders/linked doors are used in play. (*Extending Maps for Dungeons.md* is not in
      the repo — the README is the workflow doc.)
- [x] **Known Limitations** written into the README (one page simulated at a time; no
      cross-boundary combat/pursuit; portals & paging out-of-combat only; pages share a cell
      size; only the acting creature crosses) + memory note `[[floors_dungeon_manifest]]`.

---

## Serialization round-trip checklist (per repo memory rules)

- New `Cell.z` and door `z` — write **and** read in every door/terrain (de)serializer.
- New `BattleMap` origin/`z_level` — these live in the **manifest** (`dungeon.json`), not the
  per-encounter terrain file, and are re-applied on every `_switch_to_page`.
- New `ladders` array and door `link_target` — both directions in `_save_terrain` /
  `_load_terrain`, cleared on scene swap and re-applied after wall detection (same ordering
  the doors already use so closed-door Wall terrain survives — `main.py:11114`).
- Any new `rpg.Stats` / `rpg.Weapon` flags are **out of scope** here.

## Known Limitations (MVP — documented, deferrable)

- **No cross-boundary combat.** A ladder/door is a discrete transition. You cannot see, move,
  or attack across a portal; only one floor/page is simulated at a time. Monsters on a
  dormant page are frozen (their scene is on disk, not in the engine).
- **No cross-floor pursuit / initiative.** Combat is confined to one page. Fleeing up a
  ladder ends the encounter on that page.
- **Portals switch views out of combat** in the MVP; mid-combat portal use is gated behind a
  "leave combat?" prompt until cross-boundary support exists.
- **Pages must share cell size** for global coordinates to line up (the manual-grid /
  `set_uniform_grid` machinery already exists to enforce this per page).

## Open items to confirm as we build

- Ladder trigger: **auto on step** vs an explicit **"Use Ladder" action**. Default: explicit
  action (matches the door menu; avoids accidental floor changes). Revisit after live play.
- Party crossing: does the **whole party** follow through a portal, or only the acting agent?
  MVP: the acting agent; add "bring adjacent allies" later.
