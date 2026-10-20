# Dungeon levels: stacking pre-drawn maps

**Status 2026-10-19: Step 0.1, 0.3 and 0.6 agreed. Phase 1 done, committed `16a0d88`. O1
decided (b): C1 amended, edge walls block. 0.4 and 0.5 approved. Phase 2A done 2026-10-19
(committed `65a0698`). Phase 2B under way (steps 1–2 committed `b6fa70f`, step 3 the edge tool `0636dfd`, step 4 the edge-door tool `5421165`); 0.2 gates Phase 3.**

The goal: take a published multi-level dungeon, drawn as a set of PNGs, and make it one
traversable dungeon. Every level sits on its own floor of the shared global (X, Y, Z) grid,
aligned with the levels above and below, connected by stairs, and with its walls actually
blocking movement and sight.

Castle Ravenloft (`encounters/Castle Ravenloft/`) is the worked example and the acceptance
test: when it can be walked from the catacombs to the High Tower Peak, this plan is done.

## What already exists

The floors machinery from `plans/archive/FLOORS_IMPLEMENTATION_PLAN.md` does most of the
bookkeeping already:

- **The manifest** (`gui/dungeon.py`, `<name>.dungeon.json`): pages, each with a PNG, an
  encounter base, and a global origin `[gx, gy, z]`. Several pages may share a floor.
- **Add Page…** adds a PNG east of the current floor's pages. **The Pages overview** edits
  each page's origin with X/Y/Z steppers. It draws each page as a box, not its artwork.
- **Set Grid…** calibrates each page on its own (`manual_grid` in its `_terrain.json`,
  including `square_ft`). Pages drawn at different pixel scales still share a grid in cells.
- **Ladders** are vertical portals in a page's `_terrain.json`, with a global target.
  `_use_ladder` carries a creature to the target page.
- **Paired ladders** (`493375a`, 2026-10-19): placing or removing a ladder in the terrain
  editor writes or removes the return ladder on the landing page.

## What is missing

1. **Alignment.** Nothing shows two floors together. Lining up a basement means guessing an
   origin, switching floors, and comparing by eye.
2. **Several levels on one sheet.** `spires_of_ravenloft.png` holds Maps 6–10, which are
   five floors. A page is a whole PNG.
3. **Stairs that land elsewhere.** A ladder's exit is always the same (X, Y) one floor up or
   down. That suits spiral stairs. A straight flight comes out offset, and there is no way
   to set its exit.
4. **Walls in drawn maps.** Measured 2026-10-19 on `main_floor_ravenloft.png` with its saved
   16 px grid:
   - The detector marks a cell as wall when its *mean* grey is under `dark_cell_threshold`
     (default 40). These maps draw walls as mid-grey bands (grey 60–90), so the default finds
     **4 cells out of 3,036**. Raising the threshold catches thick wall masses but misses thin
     walls: a band about 6 px wide on a 16 px cell leaves the cell's average light.
   - Measuring the **fraction of dark pixels** in each cell (grey < 100, fraction ≥ 0.30)
     finds 675 cells, and every outer wall comes out closed. One-cell corridors stay open.
     The false positives are **stairs** (every spiral and straight flight), **furniture**
     (pews, the banquet table, the chapel slabs) and the map frame, title and compass.
   - The flood-fill seed defaults to cell (1, 1). On these maps that cell is the paper
     *outside* the castle, so a closed outer wall blocks the whole interior.
   - Nothing in the GUI sets the threshold or the seed, and nothing can clear a detected
     wall cell. Only a door erases one, in `syncDoorTerrain`.
   - **Edge walls do not block.** `detect_edge_walls` finds strokes between cells, but
     movement and line of sight read only whole cells (`BattleMap::isBlocked`). Edge walls
     feed the flood fill and nothing else.

---

## Step 0: before any code is written

**These steps run to completion and are reviewed with the user before the first line of
implementation.** Once agreed, their results are **frozen constraints**. They change only
by the user's explicit agreement, recorded here with a date and a one-line reason.

| # | Step | Output | Done |
| --- | ---- | ------ | :--: |
| 0.1 | **Agree the constraint set.** Walk *Constraints* below line by line, amend on disagreement, then freeze. | A dated "Frozen" note on the Constraints block | ☑ 2026-10-19 |
| 0.2 | **Confirm the Ravenloft floor table.** Walk *The Ravenloft floor table* below and resolve its open items: which circle in Maps 9 and 10 the small tower becomes, and whether Maps 9 and 10 need one page per circle. | The table, with no open items | ☐ |
| 0.3 | **Decide how a sheet becomes several pages.** Choose between (a) cropping the sheet into separate PNGs beside the manifest, through an in-app tool, and (b) a crop rectangle stored on the page in the manifest. See *Phase 3* for the trade-off. | A decision line in Phase 3 | ☑ 2026-10-19: (a) |
| 0.4 | **Write the wall-detection schema on paper.** The new detection mode's parameters and defaults, the per-page `detection` block in `_terrain.json`, how the flood seed is stored, and the representation of an erased wall cell. See *Phase 2*. | A schema block in Phase 2 | ☑ 2026-10-19 |
| 0.5 | **Measure every Ravenloft page.** With a throwaway script in the container (scratch dir, never committed), run the dark-fraction probe on each page with a hand-set grid. Record per page: the cell size, the threshold and fraction that close the walls, the flood seed, and roughly how many cells need erasing (stairs, furniture). This sets Phase 2's defaults from evidence, not from one map. | A table in Phase 2 | ☑ 2026-10-19 |
| 0.6 | **Review this whole document with the user.** Only then does Phase 1 begin. | The user's go-ahead, dated | ☑ 2026-10-19 (Phase 1 only; see amendment) |

Steps 0.1–0.4 and 0.6 are reading and writing only, with no source changes. Step 0.5 runs
scratch code in the container and changes no source.

**Amendment 2026-10-19 (user):** Phase 1 depends on none of 0.2, 0.4 or 0.5, so it starts
now. 0.2 must close before Phase 3 starts; 0.4 and 0.5 must close before Phase 2 starts.

### Constraints (frozen 2026-10-19 at 0.1, as written)

- **C1: Walls stay whole cells.** This plan makes cell-based walls work on drawn maps. It
  does not make edge walls block movement or sight. That would change movement, line of
  sight and NPC pathing in the C++ engine, and is deferred. If the coarse model proves too
  coarse in play, it gets its own plan.
- **C2: Old saves load unchanged.** Every new manifest or `_terrain.json` field is optional,
  and an absent field means today's behaviour. The manifest stays `version: 1`.
- **C3: Today's detection stays the default.** The new detection mode is opt-in per page.
  A page with no `detection` block detects exactly as it does now, so
  `test_determinism.py` stays byte-identical.
- ~~**C4: One square size per dungeon.**~~ **Dropped 2026-10-19 (user):** every page is in
  5-ft engine cells whatever its `square_ft`, so pages at different scales share the global
  grid. (Was: every page in a dungeon must have the same `square_ft`. A page that differs gets a warning when it is
  added or re-gridded. It is not rescaled.)
- **C5: Pairing stays as committed.** Paired ladders (`493375a`) keep their rules. A custom
  ladder exit (Phase 4) pairs through the same `_pair_ladders` path.
- **C6: The dungeon generator is untouched.** Its pages, ladders and regions are not
  changed by this plan.
- **C7: Container only.** Every build, test and GUI check runs in `rpg_map`. GUI behaviour
  is checked through `tests/gui_driver.py` and saved PNGs.

**Amendment to C1, 2026-10-19 (user, O1 = (b)):** C1 is replaced by **C1′: edge walls
block.** A wall may lie on the edge between two cells, and it blocks movement, line of sight
and NPC pathing in the C++ engine, as scoped in Phase 2A. Whole-cell walls stay as they are.
Reason: 0.5 measured that whole-cell walls at the printed 10-ft scale cannot hold these maps.
The work is a phase of this plan, not a separate plan. "Phase 2" in Step 0 now means 2A,
then 2B.

**Standing rules** (from the earlier plans, unchanged): no phase starts until the previous
phase is green and this file records what happened. No phase bundles an unrelated fix; a
fix found along the way is written down and done separately. Every phase leaves
`tests/run_all_tests.py` green.

### The Ravenloft floor table

All maps are 1 square = 10 ft. "Landmark" is what lines a page up with the floor below.

| Floor | Page | Source PNG | Landmark for alignment | Status |
| ---: | --- | --- | --- | --- |
| 7 | Map 10 | `spires_of_ravenloft.png` (crop) | small tower, from Map 9 | **open:** which circle |
| 6 | Map 9 | `spires_of_ravenloft.png` (crop) | small tower, from Map 8 | **open:** which circle; one page or two |
| 5 | Map 8 | `spires_of_ravenloft.png` (crop) | big-tower shaft (top circle, with artwork); small spiral-stair circle continues up to Maps 9–10 | confirmed |
| 4 | Map 7 | `spires_of_ravenloft.png` (crop) | big-tower shaft (top dark circle) | confirmed |
| 3 | Map 6 | `spires_of_ravenloft.png` (crop) | big-tower shaft (large dark circle) | confirmed |
| 2 | Rooms of Weeping (Map 5) | `rooms_of_weeping_ravenloft.png` | castle outline, spiral stairs | confirmed |
| 1 | Court of the Count (Map 4) | `court_of_the_count_ravenloft.png` | castle outline, spiral stairs | confirmed |
| 0 | Main Floor (Map 3), **entry** | `main_floor_ravenloft.png` | — | confirmed |
| −1 | Larders of Ill Omen (Map 11) | `larders_of_ill_omen_ravenloft.png` | stairs up to the main floor | confirmed |
| −2 | Dungeons and Catacombs (Map 12) | `dungeons_and_catacombs_ravenloft.png` | stairs up to the larders | confirmed |

User confirmation, 2026-10-19: the big tower's dark shaft is one tower through Maps 6, 7
and 8 (in Map 8 it carries artwork). The small spiral-stair circle in Map 8 continues into
Map 9 and on to Map 10.

`walls_of_ravenloft.png` and `area_k73_ravenloft.png` are in the folder but not in the
table. They are out of scope unless added at 0.2.

**The current state of the example**, for reference: the manifest holds two pages, Main Floor
(66 × 46, from a manual 16 px grid) and Court of the Count. The Court page records
**31 × 60**, which is a misread automatic grid. It needs Set Grid… before alignment means
anything. Main Floor has wall detection switched off.

---

## Phase 1: the floor overlay (alignment)

**Goal:** see the floor below (or above) through the current page, and nudge the current
page's origin until the two line up.

- An **Align Floor** mode on the main map. It draws the pages of floor z − 1, or z + 1 on a
  toggle, semi-transparent under the current page's artwork. Each ghost is placed at its own
  global origin and scaled so its cells match the current page's cells. Pages with
  different pixel scales still line up cell for cell.
- The ghost's cell size comes from its `manual_grid`. If it has none, a headless
  `rpg.BattleMap` analyses its PNG. A ghost page with no usable grid is skipped, with a
  message naming it.
- **Arrow keys** move the current page's origin one cell. Enter saves the manifest; Esc
  restores the origin the mode started with.
- The renderer is a function of its own, because Phase 4's exit picker reuses it.

**Tests.** A ghost page's cell (c, r) is drawn over the current page's cell for the same
global (X, Y), for two pages with different cell sizes and offset origins. A nudge moves the
origin by exactly one cell, and Enter persists it. Esc restores the origin. A ghost with no
grid is skipped, not drawn wrong.

**Done 2026-10-19.** `gui/floor_overlay.py` (`ghost_placement`, `load_ghost_lines`,
`draw_ghosts`, the `FloorAlign` mode); Dungeon Configuration → **Align Floor**. Tab flips
between the floors below and above. If the floor below has no pages, the mode opens on the
floor above. Changing pages mid-align cancels the nudge. `tests/test_floor_align.py` has 8
tests, and the full suite passes (173/0). A headless render of the Ravenloft pages lined the
Main Floor ghost up under the Court page's grid.

Two departures from the text above, both forced by the drawing:
- The ghost is drawn **over** the current page's art at partial alpha, not under it. The
  page art is opaque, so anything under it would be invisible.
- A nudge **pans the map with the page**: the ghost floor stays put on screen and the
  current page slides over it.

**User steps after Phase 1:** Set Grid… on each page, then Add Page… for each level and set
its Z, then align each floor to the one below it.

## Phase 2A: edge walls block (engine)

**Goal:** a wall on the edge between two cells stops movement, line of sight and NPC
pathing, and a door on a wall line opens and closes that edge. Scoped 2026-10-19 under C1′.
This phase is engine and bindings only. Detection and the editing UI are Phase 2B.

**Where blocking is decided today** (audited 2026-10-19). Every rule funnels through a small
number of functions:

| Path | Function | Reads today |
| --- | --- | --- |
| Walk / fly / climb step | `moveAgent`, `pathfindMovement` (→ `reachableCells`) | `isBlocked(next)` per Dijkstra step |
| Jump | `jumpAgent` | `isBlocked` per step of a straight trace |
| Push / pull | `forceMoveAgent` | `isBlocked` per step |
| Placement | `spawnAgent`, `applyAgentConfigs`, `setAgentPosition` | `isBlocked(origin)` |
| Sight, ranged attacks, spell targeting, AoE pruning, cover, hiding, fog | `hasLineOfSight` (≈ 40 callers, `canSee`, `revealFogForFaction`, `pruneBlockedCells`) | `disallowed_` and Wall terrain on the 2× sub-grid |
| Opportunity attacks | `combat_movement.cpp` `threatens` (LOS plus the 5-ft corner rule) | wall cells |
| NPC movement | `combat_turn.cpp` (flee, approach) | `reachableCells` and LOS |
| Python | `helpers.py`, `net/move.py`, `net/picks.py`, `net/view.py`, `main.py` jump preview | `is_blocked`, `reachable_cells`, `has_line_of_sight` |

So the change is three engine primitives, plus the callers that test adjacency by hand.

**The edge store.** A per-cell bitmask `edgeMask_` (`rows × cols` bytes): bit E is the edge
between (c, r) and (c+1, r), bit S is the edge between (c, r) and (c, r+1). Lookup is O(1).
It is separate from `walls_`, which keeps feeding today's flood fill and nothing else. An
empty mask (the default, and every existing page) takes a fast path that skips every edge
test, so `test_determinism.py` cannot move (C3).

**The three primitives:**

- `edgeBlocked(Cell a, Cell b)`, for orthogonal neighbours. True when the shared edge is set.
- `stepCrossesWall(Cell from, Cell to, int size)`, for one step of a size-n footprint. Every
  footprint cell moves by the same (dc, dr). An orthogonal move is blocked when any cell's
  step crosses a set edge. A diagonal move goes through a corner, and **a corner blocks when
  both L-shaped routes around it are walled**: (c, r) → (c+1, r+1) is open if
  E-then-S or S-then-E crosses no edge. A wall that ends at the corner, or turns there, lets
  the diagonal past. A straight wall through the corner stops it.
- `footprintSplit(Cell origin, int size)`: true when a set edge lies inside the footprint.
  A Large creature cannot stand across a wall. `isBlocked` calls it, so placement and every
  "can I end here" check get it free.

**Wiring:**

- `moveAgent`, `pathfindMovement`, `forceMoveAgent` add `stepCrossesWall(cell, next, size)`
  beside each `isBlocked(next)`.
- `jumpAgent` checks each consecutive pair of its trace.
- `hasLineOfSight`: in `los1x1`, a step of the sub-grid walk that lands on an even x (odd y)
  crosses a vertical grid line, and is blocked by that edge. An even y (odd x) crosses a
  horizontal line. An even-even corner uses the corner rule above. Edges inside either
  footprint are ignored, as footprint cells are today.
- **Opportunity attacks** and any other hand-written adjacency test: a 5-ft orthogonal
  neighbour across a set edge is not reachable, and a diagonal one follows the corner rule.
  Part of the phase is to grep every hand-rolled adjacency check (grapple, shove, Help,
  touch spells, OA) and route it through one helper, `meleeStepOpen(a, b)`. The list goes
  in this file when it is done.
- **Teleport** ignores edges, as it ignores wall cells today.

**Doors on edges.** A `Door` gains an optional `edges` list, each entry `(c, r, E|S)`, up to
four contiguous edges, as a wide door spans up to four cells today. `syncDoorTerrain` clears
the door's edge bits when it is open and sets them when it is closed. A door with `cells`
works exactly as before. The door's state is applied after detection (the Phase 2B order
already puts doors last), so a dark door icon detected as wall never overrides the door.
`doorAt` gains an edge form for the GUI. In `_terrain.json` a door entry may carry `edges`
in place of `cells` (C2: absent means a cell door).

**Bindings** (snake_case): `set_edge_wall(c, r, side, on)`, `is_edge_wall(c, r, side)`,
`edge_walls` (read-only list of `(c, r, side)`), `clear_edge_walls()`, `step_crosses_wall`,
and `edges` on the door binding and `add_door`. `clear_walls()` also clears the mask.

**Python callers:** `helpers.py`, `net/move.py`, `net/picks.py` and `net/view.py` get the
engine's answer through `is_blocked` / `reachable_cells` / `has_line_of_sight`, so they need
no logic of their own. Each one is read to confirm it doesn't step through cells by hand.
The `main.py` jump preview gets `step_crosses_wall` along its line. A debug overlay draws
set edges as thick lines when the Walls display is on.

**Performance.** One byte lookup per step and per sub-grid line crossing. Measure
`reachable_cells` from the centre of a 66 × 46 map at 60 ft, and a full NPC automation turn,
before and after, with an empty mask and with Main Floor's ~1,500 edges. Record the numbers
here. The target is no measurable change with an empty mask.

**Tests** (`tests/test_edge_walls.py`, registered in the runner):
- An edge between two open cells stops a walk across it, and the path goes round. The
  reachable set excludes the far side when there is no way round.
- Diagonals: a straight wall through a corner stops the diagonal. A wall that ends at the
  corner, or turns there, doesn't.
- A Large creature can't be placed across an edge, can't step through a gap one cell wide,
  and can walk along the wall.
- Jump and push stop at an edge.
- LOS: blocked across an edge, open along it, the corner rule, and symmetric in direction.
  A ranged attack and an AoE stop at the edge. Fog doesn't reveal past it.
- An OA doesn't fire across an edge between adjacent cells. Melee can't reach across it.
- An edge door blocks when closed, passes when open, and survives open → close → open.
  A cell door behaves exactly as before.
- NPC automation paths round an edge wall.
- An empty mask leaves `test_determinism.py` byte-identical and every existing suite green.

**Done 2026-10-19** (uncommitted). Engine: `Edge` / `EdgeSide`, a per-cell `edgeMask_`
(static wall, door-owned and door-shut bits for the east and south edges), `edgeBlocked`,
`edgeBetween`, `stepCrossesWall`, `footprintSplit`, and `addEdgeDoor` / `doorAtEdge`.
Movement (`moveAgent`, `pathfindMovement`, `jumpAgent`, `forceMoveAgent`), placement
(`isBlocked`) and `hasLineOfSight` read them. Line of sight tests the exact segment between
cell centres against each grid line it crosses, so it is symmetric by construction. A new
grid drops static edges and re-applies edge doors. Bindings as listed above, plus
`last_move_path`. The Walls overlay draws edge walls on the grid lines.
`tests/test_edge_walls.py` has 21 tests. The full suite passes (174/0) and
`test_determinism.py` is byte-identical.

Departures and additions:
- **The NPC driver's `canAttackFrom` now requires line of sight for melee too**, as
  `canAttack` already did. The edge test caught an NPC attacking diagonally through a wall.
  On maps without edges this changes nothing at 5 ft (the golden didn't move). A reach
  weapon round a wall *cell* is now also refused, which is the rule.
- **The adjacency audit.** Of the `footprintDistance` checks with no line of sight beside
  them, most are rules that say "within X ft" and ignore walls by design: auras, Sneak
  Attack's ally, Pack Tactics-style advantage, Mage Hand / Invoke Duplicity, Lion aura,
  Dark One's Blessing, Elder Champion, the NPC targeting and flee heuristics. Left alone.
  The physical touches now also require line of sight: **grapple and shove**
  (`executeGrapple`, `executeShove`: "A wall is in the way."), **freeing a netted
  creature** (`escapeNet`, and the GUI's `_netted_within_reach`), and **Cleave's second
  target** (GUI). They share one Python helper, `_can_reach_through`. The opportunity
  attack needed nothing: its `hasLineOfSight` test now sees edges.
- The empty-mask fast path is tested at the call site (`edgesActive_ &&`), not inside the
  functions. Without that, reachability with no edges was ~5% slower than HEAD.

**Performance** (container, 67 × 46 grid, `reachable_cells` from mid-map, 20,000 random LOS
pairs, median of 15 NPC turns; HEAD built from `16a0d88` in a scratch dir):

| Build | Edges | reach 60 ft | reach 120 ft (Large) | LOS / pair | NPC turn |
| --- | ---: | ---: | ---: | ---: | ---: |
| HEAD | 0 | 88 µs | 360 µs | 0.29 µs | 200 µs |
| Phase 2A | 0 | 87 µs | 345 µs | 0.29 µs | 195–204 µs |
| Phase 2A | 810 (6-cell rooms, doorways) | 83 µs | (walled in) | 0.34 µs | 260–285 µs |

No change with an empty mask. With rooms, LOS costs ~17% more per pair, and an NPC turn ~35%.

**Still to do in 2B, found here:** the GUI draws doors from `cells`, so an edge door has
nothing to draw or click until 2B's door tool. `door_at(cell)` doesn't find edge doors;
use `door_at_edge`.

**Not in this phase:** detecting edges from art, the outside flood, the Floor brush and
edge overrides UI (Phase 2B); half-height walls or edges that block sight but not movement.

**Decided 2026-10-19 (user):**
- **The diagonal corner rule:** a diagonal step is open when either L-shaped route around the
  corner is clear. A straight wall through the corner blocks it. A wall that ends or turns at
  the corner does not. The same rule applies to movement, line of sight and melee reach.
- **Doors on drawn maps are edges.** A door entry carries `edges`, and doors made of cells
  keep working as before.

## Phase 2B: wall detection for drawn maps

**Goal:** a drawn map's walls block, with a first pass from detection and the misses fixed
by hand.

**Progress 2026-10-19 (uncommitted): the engine half and the file are done.** Dark-fraction
cells, edge detection into the Phase 2A edge mask, the outside flood, the `detection` block,
`edge_overrides` and Floor regions are applied on load, Walls toggle and editor close
(`App._redetect_walls`); Set Grid… clears seeds and overrides. `rpg.DetectionMode`,
`BattleMap.allow_cell`. 15 tests in `tests/test_drawn_wall_detection.py`, suite 175/0.
One addition to the schema's C++ side: `DetectionParams` also carries `edgeAdd` /
`edgeRemove`, so the outside flood sees the DM's overrides (an added edge closes a leak).
The flood reads static edge walls only, never door state, so it doesn't depend on whether
doors are placed yet. Still to do: the UI (Floor brush, detection controls and seed click,
grid-line edge tool, edge-door tool and saving edge doors), and the Catacombs leak.

**Decisions 2026-10-20 (user), after probing Ravenloft at 10 ft (16 px cells, 2×2 per square):**
- Detection is a first pass; the DM fixes the rest by hand. At 16 px cells the per-cell edge
  test also marks one-cell "ticks" where a wall crosses a grid line at right angles (they can
  close a 10-ft corridor), and decorations (pews, stairs, pillars) block. A stub-pruning rule
  was prototyped (it removes the ticks with no new leak on Main Floor) but **not adopted**:
  the hand tools have to handle decorations anyway.
- So the edge tool works by **drag**, not click: drag along a grid line adds or removes a run
  of edges, and a box-erase removes every edge inside it.
- **The Floor brush also clears a border edge whose far cell is a wall cell.** Such an edge
  only duplicates the wall cell, so clearing it opens nothing new, and a cleared staircase
  isn't left fenced in by its own rim.
- Build order: detection controls + seed click, Floor brush, edge tool, edge-door tool.

**Progress 2026-10-20 (uncommitted): steps 1 and 2 done.** Terrain… → **Wall Detection…**
(only while Walls is ON) opens a dialog docked over the panel: detector Mean / Drawn, edge
walls on/off, dark level, cell and edge fractions (as %), band half-width, seed count and
Clear. Every change re-detects and redraws; in Drawn mode a click on the map toggles an
outside seed (green dot). OK saves the block (not if it was never switched to Drawn);
Cancel restores. The terrain editor now shows the detected cells and edges, and **[7] Floor**
drags a box that clears them, previewed live. The panel's "Walls:" count includes edge walls.
`tests/test_drawn_wall_detection.py` 22 tests, suite 175/0. Next: step 3, the edge tool.

**Progress 2026-10-20: step 3, the edge tool, done (committed).** Terrain editor **[8] Edge**,
only with Walls ON and the Drawn detector (otherwise the hint says so and drags do nothing).
Left-drag snaps to the grid crossings and runs along the dominant axis: it adds the run, or
removes it when its first edge is already a wall; a click toggles the nearest edge. Right-drag
box-erases every wall edge whose midpoint is in the box. Ctrl+Z undoes edge edits. Each edit
writes `edge_overrides` (lists kept disjoint; a removal is recorded only for an edge that is
still a wall once it is out of `add`) and re-detects live; hand-added edges draw orange.
Decided while building: **Floor keeps a hand-added edge** (it clears what was detected, not
what was drawn). Empty overrides are dropped on close, so the file stays clean.
`tests/test_drawn_wall_detection.py` 28 tests. Next: step 4, the edge-door tool.

**Progress 2026-10-20: step 4, the edge-door tool, done (committed `5421165`).** With the Edge tool's
conditions (Walls ON, Drawn detector), **[5] Door** places doors on grid lines: a click
toggles a one-edge door on the nearest edge, a drag along a line places a wide one (max 4
edges), and a click on an old cell door still removes it. Otherwise Door mode places cell
doors as before. `_terrain.json` stores an edge door with `edges` (`[c, r, "E"|"S"]`) in
place of `cells`/`cell`; edge doors never carry a cross-map link (they can't sit on the page
border). Drawn as a bar a third of a cell thick on the grid line, in the editor and on the
map. A map click within 0.35 of a cell side picks the edge door there (`App._door_index_at`);
the door menu needs the actor standing in a cell either side of the line. **Knock**: the
engine now also finds an edge door from a cell beside it (east, south, west, north, in that
order; the GUI aims at a cell where the chosen door comes first), so a remote tap works too
(C++ change, rebuilt). The player view sends `edges` on the door record; the web client
doesn't draw doors yet. Pure edge helpers (`edge_key`, `edge_from_key`, `door_touch_cells`)
live in `helpers.py`. `tests/test_drawn_wall_detection.py` 33 tests, `test_picks.py` gains
an edge-door Knock; suite 175/0, determinism golden unchanged. Next: step 5, per-page
Ravenloft cleanup.

- **A dark-fraction mode** in the C++ detector: a cell is a wall when at least
  `dark_fraction` of its pixels are darker than `dark_level`. It sits alongside the mean
  test, and the mean test stays the default (C3). This needs a rebuild.
- **Per-page settings** saved in the page's `_terrain.json` as a `detection` block: the
  mode, `dark_level`, `dark_fraction`, and the flood seed. The schema is fixed at Step 0.4,
  and the defaults come from Step 0.5's measurements.
- **Set the flood seed by clicking** a cell inside the building. The flood fill then blocks
  everything the walls enclose away from it, which removes the frame, title and compass.
- **A Floor brush** in the terrain editor that clears detected wall cells (stairs,
  furniture). Cleared cells are stored as regions of a new type and re-applied after every
  detection pass, so they survive a reload and a re-detect. This needs a binding that
  removes a cell from the detected set. The representation is fixed at Step 0.4.
- **Detection controls** (mode, the two levels, the seed) in the terrain menu, with the
  blocked cells redrawn live.

**Tests.** A synthetic PNG with thin walls drawn along grid lines: the mean test misses
them and the fraction test catches them. The seed decides what the flood fill blocks.
Floor-brushed cells stay open across save, reload and re-detect. A page with no
`detection` block detects exactly as before (C3). `test_determinism.py` stays byte-identical.

**User decisions on the 0.5 findings, 2026-10-19:**
- ~~**Cells stay at the printed scale, 1 square = 10 ft.** No half-cells.~~ **Superseded
  2026-10-19 (user, option A):** the engine cell stays 5 ft, because every distance in the
  engine (movement, reach, ranges, areas, pushes, light, footprints) is hard-coded at 5 ft
  per cell. The scale is per page and configurable: Set Grid…'s `square_ft` (5, 10, 15 or
  20) makes each printed square 1×1, 2×2, 3×3 or 4×4 engine cells. Ravenloft is 10 ft, so
  2×2. Walls lie on edges (O1 = b), so the cells inside a printed square cost no room
  space; the lines through the middle of a square carry no stroke and detect nothing.
- **Grids stay integer.** The user rescales pages by hand so each engine cell is a whole
  number of pixels: a printed square must divide by `square_ft / 5` (a 10-ft square is an
  even number of px). No fractional `cell_px`.
- **The flood seed goes outside**, on the paper, and blocks what it reaches. The flood
  stops at detected walls.
- **No inset** in the new mode.

### Open item O1: how walls block at 10-ft cells (amends C1 or not)

0.5 shows that at 10-ft cells **whole-cell walls cannot represent these maps**. That holds
for walls detected automatically and for walls painted by hand. The maps draw walls *on*
the grid lines, so a wall belongs to the cells on both sides of it. Either both cells
block, and every room loses its outer ring and every 10-ft corridor closes, or neither
blocks, and the wall is absent. Measured with no inset: grey < 100 at fraction 0.06–0.15
closes every page, but it leaves the Larders almost entirely blocked and Main Floor's
rooms one or two cells across.

The same maps read as **edges** come out right. A grid-line segment counts as a wall when
≥ 30% of a ±4 px band along it is darker than 100. Main Floor, Court, Larders and Rooms of
Weeping all close, every room keeps its full interior, and the walls follow the printed
lines. The false edges are stair treads and a few interior lines. Catacombs leaks
somewhere and would need a look.

- **(a) Keep C1.** Whole-cell detection at 10 ft marks only the solid grey-70 masses
  (fraction ≈ 0.6). Thin walls don't block until the DM paints them, and a painted wall
  still costs the room a ring of cells. The plan's goal of walls that actually block is
  then not met on these maps.
- **(b) Amend C1: edge walls block movement and sight.** `detect_edge_walls` already finds
  the strokes, and `walls_` already holds them. Movement, reachability, line of sight and
  NPC pathing would have to refuse to cross a wall edge. Doors are drawn on the wall line, so an open
  door must also open the wall edges along it, and a closed door must restore them. That is a C++ engine change on the
  hot paths, and C1 says it gets its own plan. Two ways to do that: a new phase here, or a
  separate plan that Phase 2 waits on.

**Recommendation: (b).** It is the only option that meets the plan's goal at the printed
scale. If you choose it, C1 gets a dated amendment and the engine work is scoped before
Phase 2 code starts.

**Decided 2026-10-19 (user): (b), scoped as a new phase of this plan (Phase 2A).** C1 is
amended (see *Constraints*).

**Schema (filled in at Step 0.4):** _approved 2026-10-19 (user). O1 = (b), so the edge fields apply._

A page's `_terrain.json` gains an optional `detection` block:

```json
"detection": {
  "mode": "dark_fraction",
  "dark_level": 100,
  "dark_fraction": 0.6,
  "edge_walls": true,
  "edge_fraction": 0.3,
  "edge_halfwidth_px": 4,
  "outside_seeds": [[2, 12]]
}
```

| Field | Type | Default when the mode is switched on | Meaning |
| --- | --- | --- | --- |
| `mode` | `"mean"` \| `"dark_fraction"` | `"dark_fraction"` | `"mean"` is today's detector, unchanged. |
| `dark_level` | int 0–255 | 100 | A pixel is dark when its grey is below this. |
| `dark_fraction` | float 0–1 | 0.6 under (b); 0.06–0.15 under (a), per page | A cell is a wall when at least this fraction of its pixels are dark. No inset. |
| `edge_walls` | bool | true under (b) | Detect wall edges on the grid lines. |
| `edge_fraction` | float 0–1 | 0.3 | An edge is a wall when at least this fraction of its band is dark. |
| `edge_halfwidth_px` | int | 4 | Half-width of the band each side of the grid line. |
| `outside_seeds` | list of `[col, row]` | `[]` | Flood from each seed and block every cell it reaches. The flood is 4-connected and stops at wall cells and wall edges. A seed on a wall cell is ignored. Empty means no flood. |

Rules:
- **No block, or `mode: "mean"`, means today's behaviour exactly** (C2, C3): mean test at
  `darkCellThreshold`, 2 px inset, flood from `floodSeed` (1, 1) through edge walls only.
  A page is saved with a block only once its mode has been changed, so untouched pages stay
  byte-identical.
- **`walls_enabled: false` still wins.** With walls off, the block is kept but not applied.
- **Seeds are cells, so they depend on the grid.** Set Grid… on a page clears its
  `outside_seeds` and says so in the status line.
- **The order on every load and re-detect:** dark cells, then edge walls, then the outside
  flood, then Floor regions, then Wall/Chasm/Water regions, then doors. Floor comes after
  the flood, so a hand-cleared cell stays open even if the flood marked it outside. Clearing
  an outer-wall cell cannot leak the flood into the rooms.

**Clearing cells (the Floor brush):** a new region type, `"Floor"`, in the existing
`regions` list, stored the same way as the other painted regions (fit-scale pixel rect:
`type`, `x`, `y`, `width`, `height`). On apply, every detected wall cell under it leaves the
detected set. That needs a binding to remove a cell from `disallowed_`. Under (b), a Floor
region also clears the wall edges that lie wholly inside it.

**Adding and removing edges by hand (only under (b)):** an optional
`edge_overrides: {"add": [[c, r, "E"|"S"], …], "remove": […]}` in `_terrain.json`. An entry
names the east or south edge of cell (c, r), and the list is applied after detection. Set
Grid… clears it, as it clears seeds.

**C++ side:** detected edges go into Phase 2A's edge mask, not `walls_`. `DetectionParams` gains `mode`, `darkLevel`, `darkFraction`, `edgeFraction`,
`edgeHalfwidthPx` and `outsideSeeds`, and keeps `darkCellThreshold`, `floodSeed`,
`detectEdgeWalls` and `wallMinPx` with today's defaults. The defaults reproduce today's
detector, so `test_determinism.py` cannot move.


**Per-page measurements (filled in at Step 0.5):** _approved 2026-10-19 (user)._

Method: a scratch probe in the container on copies of the PNGs. Grey uses BT.601 with
alpha dropped, the same as `detectWalls`. Each page's printed 10-ft grid was measured from
its edge periodicity and checked by eye against overlays. A cell is blocked when at least
*fraction* of its pixels are darker than *level*. "Closes" means a 4-connected flood from
the paper outside does not get into the rooms.

| Page | 10-ft square (px) | Phase x, y | Whole cells, no inset: closes at | Edges (≥ 0.3 of ±4 px, grey < 100) | Half-cells, for reference |
| --- | ---: | --- | --- | --- | --- |
| Main Floor | 31.0 | 135, 94 | f 0.06–0.15; rooms shrink to 1–2 cells | closes, rooms whole | < 100 / 0.20 closes, ~200 to clear |
| Court of the Count | 32.0 | 44, 62.5 | f ≤ 0.12; same loss | closes, rooms whole | < 90 / 0.15 closes, ~250 to clear |
| Rooms of Weeping | 29.15 | 66, 61 | f 0.06–0.15; same loss | closes, rooms whole | < 100 / 0.25 closes, ~120 to clear |
| Larders of Ill Omen | 38.8 | 66, 63 | f 0.06–0.15; almost everything blocks | closes, rooms whole | < 100 / 0.25 closes, ~150 to clear |
| Dungeons and Catacombs | 22.8 | 14.5, 0.5 | f 0.06–0.15; same loss | leaks somewhere, to find | < 100 / 0.25 closes, ~45 to clear |
| Spires (sheet) | ~22.3 | — | not probed | not probed | waits for the Phase 3 crops (0.2) |

The pitches are fractional on most pages. Per the user's decision they become integers by
rescaling each page by hand. The rescale changes the phase, so the phase column is for
reference only.

What the measurements show:

- **Every wall and rock mass is a flat grey 70** on every page. Floors are 110–180. Court's
  throne room is the darkest floor (median about 120, 10th percentile 80–90).
- **Whole cells at 10 ft cannot hold these walls.** See O1.
- **The engine's 2 px inset defeats thin walls.** A band that straddles a grid line splits
  between two cells, and the inset trims most of what is left. The new mode does not inset.
- **Main Floor's saved grid (16 px, `square_ft` 10) is a half-square.** The printed square
  is 31 px. Main Floor needs Set Grid… at the printed square, after its rescale.
- **Doors block.** The brown door icons are dark. A placed door object clears its cells
  (`syncDoorTerrain`), so this is acceptable, but until doors are placed every room is its
  own pocket.
- **The flood fill ignores dark cells today.** `floodFillPassable` stops only at edge walls,
  so with edge walls off it reaches every cell and blocks nothing. An *inside* seed also
  fails on these maps: with doors blocking, it keeps one room and blocks the rest. A seed
  on the paper outside, blocking what it reaches, removes the frame, title and compass
  regardless of doors.
- **The big black shafts block.** In play they are drops, not walls. Painting them as Chasm
  is a DM step and is not in this plan's scope.

## Phase 3: several levels on one sheet

**Goal:** `spires_of_ravenloft.png` becomes one page per floor (or per tower; see 0.2).

**Decision at Step 0.3:**

- **(a) Crop to files.** An "Add Page from Region…" tool: drag a rectangle on a source PNG,
  and the crop is written beside the manifest as its own PNG and added as a page at a chosen
  Z. No engine change, because every page is still a whole PNG, and the tool works for any
  multi-map sheet. It leaves derived PNGs in the dungeon folder.
- **(b) A crop rectangle on the page.** No derived files, but the C++ map loader and wall
  detection read the image path directly (`cv::imread`), so either the engine learns about
  crops or the app writes a temporary cropped file anyway.

**Decided 2026-10-19 (user): (a), crop to files.**

**Tests (for (a)):** the crop file's pixels equal the source region. The new page's
footprint comes from the crop's grid. Two crops of one sheet become two independent pages.

## Phase 4: stairs that come out elsewhere

**Goal:** a ladder's exit can be any cell on the target floor.

- In the terrain editor's Ladder mode, a key switches to **Pick Exit**. Phase 1's renderer
  shows the target floor, and a click there sets the exit to that global cell.
- Pairing (C5) writes the return ladder at the picked cell, pointing back.
- **Decided 2026-10-19 (user):** stairs get no glyph of their own. A custom exit uses the
  ladder icon.

**Tests.** A picked exit is stored as the clicked global cell. Its return ladder lands
there and points back. Using the ladder in play lands the creature on the picked cell.

---

## Found along the way (separate from this plan)

- **Grapple and shove measure origin to origin** (`executeGrapple`, `executeShove`:
  Chebyshev between top-left cells), not `footprintDistance`. A Large creature is refused
  targets it touches. Found in Phase 2A; not fixed there.
- **The jump preview checks only the landing cell** (`main.py`, the jump-reach overlay), so
  it offers landings behind a wall that `jump_agent` then refuses. True for wall cells
  before Phase 2A, and now for edges too.
- **Zones along a move use a straight line** (`getCellsAlongPath(oldOrigin, newOrigin)` in
  `combat_movement.cpp`), not the route taken, so a creature that walks round a wall can be
  charged for a zone on the far side of it.
- **"Can see within X ft" rules check only distance** (Protection, Warding Flare, Beguiling
  Magic and others). The same with wall cells; not an edge-wall issue.
- **Item use at range** (`combat_resources.cpp`, item `range`) checks only distance.

- **Generated-dungeon regions may be in the wrong units.** The dungeon generator writes
  Wall regions in native image pixels (`_regions_from_grid`, `gui/main.py`), while the
  terrain editor and the region-to-cell conversion use fit-to-window pixels. These agree
  only when the map is not scaled down to fit. Not verified against a generated map larger
  than the window. Check and fix separately (C6 keeps it out of this plan).
