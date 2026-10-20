# Dungeon levels: stacking pre-drawn maps

**Status 2026-10-19: Step 0.1, 0.3 and 0.6 agreed. Phase 1 done (uncommitted). 0.4 and
0.5 gate Phase 2; 0.2 gates Phase 3.**

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
| 0.4 | **Write the wall-detection schema on paper.** The new detection mode's parameters and defaults, the per-page `detection` block in `_terrain.json`, how the flood seed is stored, and the representation of an erased wall cell. See *Phase 2*. | A schema block in Phase 2 | ☐ |
| 0.5 | **Measure every Ravenloft page.** With a throwaway script in the container (scratch dir, never committed), run the dark-fraction probe on each page with a hand-set grid. Record per page: the cell size, the threshold and fraction that close the walls, the flood seed, and roughly how many cells need erasing (stairs, furniture). This sets Phase 2's defaults from evidence, not from one map. | A table in Phase 2 | ☐ |
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
- **C4: One square size per dungeon.** The global grid counts cells, so every page in a
  dungeon must have the same `square_ft`. A page that differs gets a warning when it is
  added or re-gridded. It is not rescaled.
- **C5: Pairing stays as committed.** Paired ladders (`493375a`) keep their rules. A custom
  ladder exit (Phase 4) pairs through the same `_pair_ladders` path.
- **C6: The dungeon generator is untouched.** Its pages, ladders and regions are not
  changed by this plan.
- **C7: Container only.** Every build, test and GUI check runs in `rpg_map`. GUI behaviour
  is checked through `tests/gui_driver.py` and saved PNGs.

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

## Phase 2: wall detection for drawn maps

**Goal:** a drawn map's walls block, with a first pass from detection and the misses fixed
by hand.

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

**Schema (filled in at Step 0.4):** _pending_.

**Per-page measurements (filled in at Step 0.5):** _pending_.

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

- **Generated-dungeon regions may be in the wrong units.** The dungeon generator writes
  Wall regions in native image pixels (`_regions_from_grid`, `gui/main.py`), while the
  terrain editor and the region-to-cell conversion use fit-to-window pixels. These agree
  only when the map is not scaled down to fit. Not verified against a generated map larger
  than the window. Check and fix separately (C6 keeps it out of this plan).
