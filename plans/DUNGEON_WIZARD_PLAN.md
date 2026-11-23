# Dungeon wizard: building multi-floor dungeons from premade maps

**Status 2026-11-22: Step 0 frozen (signed off by the user, after a grilling session). W1 committed 0daac9a. W2 applied 2026-11-23 after the user checked the overlays (268/0), committed dc6021a. W3 committed a66a434 (269/0). W4 committed d7d6596 (270/0). W5 committed 6149629 (271/0). W6 committed a21e915 (272/0). W7 committed (273/0). W8 committed (273/0). W9 next on go.**

The problem (user, 2026-11-22): building a multi-floor dungeon from published maps is
confusing. You open a map, *then* make a dungeon, *then* add a page, *then* set its grid,
*then* move it to its floor in the Pages overview, *then* align it, *then* place
staircases. These are separate menu entries with nothing linking them. On top of that, most
published multi-floor dungeons come as **one sheet holding several levels**, which today
has to be cropped outside the app (`DUNGEON_LEVELS_PLAN.md` Phase 3 was decided and
never built).

The fix: a single **Dungeon** button and a **New Dungeon wizard** that walks from the
source sheet to stacked, aligned floors. A per-floor checklist then covers everything
that's left.

## What exists today (read 2026-11-22, not run)

- Panel buttons **Generate Dungeon** (`btn_generate_dungeon`, `app_dungeon_gen.on_generate_dungeon`)
  and **Dungeon Configuration** (`btn_dungeon`, `menus/dm.show_dungeon_menu`).
- New Dungeon (`app_dungeon_pages.dungeon_new`) needs a gridded map open first.
- **Add Page…** (`on_add_page_png_chosen`) always adds to the current floor, east of its
  pages. A page added with no grid is saved as 0×0. In a campaign (v2) dungeon it writes a
  v1-style `<stem>_<page>_agents.json` beside `dungeon.json` and doesn't copy the art into
  the library, but v2 pages find their image by name through `layout.image(page.id)`. So
  Add Page probably doesn't work properly in campaign dungeons (unreproduced; the stray
  `castle-ravenloft/dungeon_TestGrid12x12_agents.json` fits).
- **Pages / Overview…** draws pages as boxes and edits origins with X/Y/Z steppers.
- **Align Floor** (`floor_overlay.py`) shows the neighbouring floor faded in; arrows nudge, Tab flips, Enter saves.
- Staircases: terrain-editor tool [9], one end per editor visit.
- Existing linked content:
  - Ravenloft's `spires-of-ravenloft.png` (1096×734) is in the library. Its floor crops
    (`spires-map6`, 816×640, …) were **enlarged** when they were cut.
  - Argynvostholt's sources are loose JPEGs in `Curse of Strahd/maps/` (lower 4800×6600,
    upper 2400×3300). Its six floors are **shrunk** crops of them.

## Step 0: frozen 2026-11-22

### Menu
- **D1.** One top-level **Dungeon** panel button replaces Generate Dungeon and Dungeon
  Configuration.
  - *No dungeon open:* New Dungeon…, Open Campaign…, Open Dungeon…
  - *Dungeon open:* **Floors…**, Staircases…, **Populate Floor…**, Show/Hide Room Labels,
    Save Dungeon, Save Game, Release / Releases… / Reset Dungeon / Undo Reset,
    New Dungeon… (inside a campaign), Open Campaign…, Open Dungeon…, Close Dungeon.
- **D2.** Pages / Overview…, Add Page… and Align Floor are no longer separate menu
  entries. They live inside **Floors…** (the overview, Add, alignment, set entry, remove).
- **D3.** The generator's "Terrain: Keep (mobs only)" becomes **Populate Floor…**, which
  fills the current floor of an open dungeon. Creating a dungeon always goes through the wizard.

### Wizard shape
- **D4.** **New Dungeon…** needs no map open.
- **D5.** The wizard is a **step panel docked over the right-hand panel** (like Wall Detection),
  with Back / Next / Cancel. The map view is its working area.
- **D6.** It is refused during combat. While it is open, connected players see **"The DM is
  preparing the dungeon…"** instead of the map.
- **D7.** **Every step saves as it goes.**
  - **Back** reopens an earlier step for editing: re-cropping overwrites that floor's image,
    re-aligning moves it.
  - **Cancel** keeps everything saved and says "Continue with Dungeon → Floors… → Add".
  - **Discard dungeon** is a separate, explicit button.
- **D8.** The first screen is today's D1 choice: an existing campaign / New campaign… /
  No campaign (loose), plus the dungeon name. Then **Start from: Premade maps / Generate**.
  Generate opens today's generator settings and builds into the dungeon just named.
- **D9.** It works the same for campaign and loose dungeons. Crops go to
  `<campaign>/maps/<name>/` in a campaign, and beside the manifest when loose.

### Premade path
- **D10. Order:**
  1. Pick an image.
  2. Set Grid.
  3. Crop a floor.
  4. Name it.
  5. Add another floor, from the same sheet (back to step 3, grid kept) or another image
     (back to step 1), or Finish.
  6. Each floor after the first: place it, then align it.
  7. Finish opens the checklist.
- **D11. Sources and images.** Any mix of sources in one run: sheets with several levels
  and single-level images. The image comes from a file or from the campaign library.
- **D12. Source sheet kept.** A picked image is copied into the dungeon as a **source**
  (not a floor), with its grid remembered. Later re-crops and Floors… → Add from a sheet
  don't ask for the grid again.
- **D13. Grid.** Set Grid runs once per sheet, and every crop inherits that grid. Set Grid
  asks for the **square size** (5 / 10 / other; default is the last sheet's). Pages stay in
  5-ft engine cells, as now.
- **D14. Crop shape.** Rectangles only, **snapped to the sheet's grid**. "Whole image" is
  one click. An optional **blank-outside brush** paints stray neighbouring art black inside
  the crop. Polygon crops are deferred.
- **D15. Crop size.** A crop keeps the sheet's resolution, **shrunk when its longest side is
  over 2048 px**. The scale is recorded with the crop.
- **D16. Name.** Each floor's name defaults to `<dungeon>-floor-<N>`, and that name is also
  the map folder in a campaign.

### Placement and alignment
- **D17.** The first floor is **floor 0 and the entry**. The entry can be changed later in
  Floors….
- **D18.** A later floor is placed **above / below / beside** an existing floor. Nobody types
  a Z. *Beside* aligns against that floor's maps, with the floor below shown faint for context.
- **D19. Alignment.**
  1. Click a **landmark pair**: a point on the new floor, then the same point on the faded
     floor. The app computes the offset.
  2. Arrow keys fine-tune it, and Enter accepts.
  3. **Skip** puts it at the same corner as the floor below.

### Finish and after
- **D20.** Walls, doors and staircases are **not** wizard steps.
- **D21. Checklist.** Finish, and Floors…, show one row per floor:
  grid ✓ · aligned ✓ · walls (none / detected / edited) · doors N · staircases N · creatures N.
  Each column jumps to that floor with the right tool open.
- **D22.** **Floors… → Add** reruns the premade steps (D10 steps 1–6) on an open dungeon.
- **D23. Staircase tool, last step of this plan.** The other floor is shown faded in, so end A
  (this floor) and end B (the faded floor) are placed in one editor visit. It reuses the
  alignment overlay.

### Existing content
- **D24. Link, don't re-crop.** Floor images are not touched. Metadata is written so the
  existing floors match the new model.
  - **Castle Ravenloft:** the spires floors point at `spires-of-ravenloft` as their source
    sheet, with a crop rectangle and scale. Single-level floors are their own source.
  - **Argynvostholt:** the two JPEGs are **copied** into `maps/argynvostholt-lower/` and
    `maps/argynvostholt-upper/` as sources. The loose files stay. Each floor points at its
    sheet with a crop rectangle and scale.
  - Rectangles and scales are found by image matching, and the user checks them by eye
    before anything is written.
- **D25. random_encounters starts clean.** The user removes `bad-pixies/`, `test/` and
  `_archive/` after a backup. `campaign.json`, `pcs/`, `session.json` and the empty `maps/` stay.
- **D26.** Everything else, including v1 loose dungeons, opens unchanged. New fields are
  optional (as `DUNGEON_LEVELS_PLAN.md` C2).

**Standing rules:**
- No step starts until the previous one is green and recorded here.
- No step bundles an unrelated fix.
- Every step leaves `tests/run_all_tests.py` green, in the container.
- GUI behaviour is checked through `tests/gui_driver.py`.

## Steps

| # | Step | Done |
| --- | ---- | :--: |
| W1 | **Data model.** Source sheets and floor crop metadata. Readers and writers in `dungeon.py` / `save_layout.py`, all fields optional (D26). | ✅ |
| W2 | **Link existing content** (D24). One-off tool, dry run first, overlay PNGs for the user to check, then `--apply`. | ✅ |
| W3 | **Dungeon button and menu** (D1–D3). Merge the buttons, add the Floors… entry that holds the old overview/add/align, split out Populate Floor…. | ✅ |
| W4 | **Wizard shell** (D4–D8). Docked step panel, Back/Next/Cancel/Discard, combat refusal, player placeholder, saving at each step, first screen, Generate path. | ✅ |
| W5 | **Source, grid, crop, name** (D10–D16). | ✅ |
| W6 | **Placement and alignment** (D17–D19). | ✅ |
| W7 | **Checklist** (D21), on Finish and in Floors…. | ✅ |
| W8 | **Floors… → Add** (D22), including re-cropping from a kept source. Replaces Add Page's v2 path. | ✅ |
| W9 | **Staircase tool with the other floor faded in** (D23). | ☐ |
| W10 | **Live check.** Build a dungeon from a fresh sheet in the real app, run by the user. | ☐ |

### W1 as built (2026-11-22)
- `dungeon.py`: `SourceSheet` (`"source": {"square_ft": N}`; a bare `true` reads as 5 ft),
  `Crop` (`"crop": {"sheet", "rect": [x, y, w, h], "scale"}`, `floor_size`),
  `read_source` / `read_crop` / `set_meta`, and `carry_meta`. A malformed block reads as none.
  `Dungeon.sources` is the loose manifest's optional `sources` list (version 1 only).
- **Settled vs. the proposal:** `"source"` is a dict holding the square size (D13), not
  `true`. The sheet's grid is the document's existing `manual_grid`.
- **Why the writers changed:** both terrain writers rebuild the design document from the
  live scene, so they would have dropped the blocks on the next save. `run_state.split_terrain`
  (campaign `map.json`) and `LegacyStore.write_terrain` (loose `_terrain.json`) now carry
  them over from the file on disk. The terrain document the app sees never contains them.
- `save_layout.py`: `Campaign.library_map_doc` / `source_sheet` / `list_sources`,
  `DungeonLayout.map_doc` / `crop`.
- Tests: `tests/test_floor_crops.py` (10 cases).

### W1 design note (the proposal it started from)
- **Campaign:**
  - A source sheet is a library map whose `map.json` has `"source": true` plus its grid.
  - A floor's `map.json` gains
    `"crop": {"sheet": "<source map>", "rect": [x, y, w, h], "scale": s}`, where `rect` is in
    sheet pixels and `s` is floor pixels per sheet pixel.
- **Loose:**
  - The same `crop` block goes in the floor's `_terrain.json`.
  - The manifest gains an optional `"sources": [{"png": …, "terrain": …}]`.

### W2 notes
- Matching runs in the container (OpenCV). Scales differ (Ravenloft enlarged, Argynvostholt
  shrunk), so it searches over scale.
- The tool writes `<floor>_match.png` overlays to a scratch folder and prints rect/scale per
  floor. Nothing is written without `--apply`, which backs up the files it changes.

### W2 as built (2026-11-22)
- `tools/link_floor_crops.py <dungeon dir> --sheet <library map | image=name> … [--out DIR] [--apply]`.
  The container has no Python OpenCV, so matching is numpy/scipy: a masked normalised
  cross-correlation swept over scale (coarse, then ±5 %), then a sub-pixel polish of
  (x, y, scale). A floor's flat padding canvas is masked out. Scores of real crops are
  0.99; anything under 0.9 is "no match" and the floor becomes its own source.
- **W1 amended:** a crop `rect` may reach past the sheet's edge (negative x/y). Castle
  Ravenloft's floors are the crop pasted on a 1216×992 canvas, so the rect that gives
  the floor's full size starts off the sheet; that part is blank padding.
- Writes on `--apply`: the floor's `crop` (or `source`, when unmatched) into the
  `map.json` the dungeon reads; the sheet's `source` mark, plus its `manual_grid` when
  the floors' 16 px cells land within 2 % of whole sheet pixels, into the library
  `maps/<sheet>/map.json`; a loose sheet is copied into `maps/<name>/`. Changed files
  are backed up once to `<file>.pre-link-crops`.
- Dry run, Castle Ravenloft (`--sheet spires-of-ravenloft`):
  spires-map6 `[326, -34, 857, 699]`, spires-map7 `[-233, -103, 857, 699]`,
  spires-map8 `[-230, 261, 857, 699]`, north-tower-roof-map9 `[34, 441, 857, 699]`, all
  at scale 1.4189, scores 0.988–0.998. tower-peaks-map9-10 scores 0.725: it is pieced
  from two places on the sheet (North Tower Peak and High Tower Peak), so it is its own
  source, with the five single-level floors. Sheet cell 11.276 px is not whole, so no
  sheet grid is written; Set Grid will ask once.
- Dry run, Argynvostholt (`--sheet maps/map-07.01-…-lower-player.jpg=argynvostholt-lower
  --sheet maps/map-07.02-…-upper-player.jpg=argynvostholt-upper`): ground
  `[120, 2874, 4562, 3609]` and second `[120, 121, 4562, 2728]` on lower at 0.2225;
  third, rooftop, beacon-1, beacon-2 on upper at ~0.445; scores 0.988–0.998. Sheet
  grids: lower 72 px anchor (26, 61), upper 36 px anchor (11, 26).
- Tests: `tests/test_link_floor_crops.py` (4 cases, synthetic sheets).
- **Applied 2026-11-23** to both dungeons. Each floor's `map.json` gained only its
  `crop` or `source` key; doors, walls, grid and the rest are byte-identical to the
  `.pre-link-crops` backups. `dungeon.json` (staircases, origins) was not touched.
- Also fixed: the DM window is re-centred after a map load resizes it
  (`app_persist._keep_window_on_screen`); a window that grew from a small first map
  ran off the right of the Xvfb display, clipping the panel.

### W3 as built (2026-11-23)
- One **Dungeon…** panel button (`btn_dungeon`, under Lighting / Items) replaces
  Generate Dungeon and Dungeon Configuration; the panel is one row shorter.
- `menus/dm.show_dungeon_menu`, titled "Dungeon":
  - *No dungeon:* New Dungeon…, **Generate Dungeon…**, Open Campaign…, Open Dungeon….
    Generate Dungeon… is **interim**: it is today's `on_generate_dungeon` (blank map →
    named dungeon, or a loose map), kept reachable until W4's wizard Generate path
    replaces it. W4 removes the row.
  - *Dungeon open:* exactly D1's list.
- `show_floors_menu` (Floors…): Overview… (the old Pages / Overview, which already holds
  Set Entry and Remove), Add… (the old Add Page…), Align Floor. W7's checklist takes it over.
- `app_dungeon_gen.on_populate_floor`: needs an open dungeon and a grid, opens
  `modal_generate_dungeon(populate=True)` (titled Populate Floor, the Floors / Rooms/map /
  N×M / Terrain rows left out, button "Populate"), forces `carve` off, and writes the
  page's own encounter through the usual overwrite confirmation.
- Strings that named "Dungeon Configuration" (staircase-tool hints, comments) now say "Dungeon".
- Tests: `tests/test_dungeon_menu.py` (7 cases); headless click-through via `gui_driver`.

### W4 as built (2026-11-23)
- `gui/dungeon_wizard.py`: `DungeonWizard` (`app.dungeon_wizard`), a step panel docked over
  the whole width of the right panel. The map beside it stays live (wheel / arrows / +/−
  reach it, as with Wall Detection). Steps are names on a stack: Back pops one.
  Enter is Next, Esc is Cancel, Tab moves between the name fields.
- **Entry points.** Dungeon → New Dungeon… (no dungeon open, and inside a campaign) and
  Open Campaign → <campaign> → New Dungeon… (that campaign preselected) open it. The
  interim Generate Dungeon… row from W3 is gone. Refused in combat (D6).
- **First screen (D8).** Campaign: every campaign, New campaign… (adds a campaign-name
  field), No campaign (loose); Dungeon name; Start from: Premade maps / Generate.
  `resolve_target` refuses, in the panel, a missing choice or name, a name with no usable
  characters, and a dungeon name already taken where it would go. **Taken names are
  refused, never replaced.** A new campaign's folder is its slug, `-2` when taken. Nothing
  is written by the first screen.
- **Where a loose dungeon lives (D9, settled here):** `maps/<slug>/<slug>.dungeon.json`
  (`app_dungeon_gen.loose_root()`, the blank map's folder), its own folder so Discard can
  archive it whole.
- **Generate (D8).** Next opens the generator's settings in a new `generate=True` shape
  (Terrain row left out, carve forced on). Cancelling them leaves the wizard and the
  scene. Otherwise the blank map is loaded if it isn't showing (`load_blank_scene`: a
  dungeon page is saved first, the campaign left), then:
  - campaign: `generate_named_dungeon(…, camp_root=, camp_name=, replace=False)`, which
    now takes the campaign (default still random_encounters for the old blank-map path);
  - loose: `generate_loose_dungeon`, built in a scratch folder under `maps/`, the blank
    image copied in, renamed into `maps/<slug>/` whole, then opened.
  The wizard closes on success. (W7's checklist will follow Finish.)
- **Premade maps.** Next goes to step 2, "Pick an image", which for now only says it
  arrives in W5; Back / Cancel work.
- **Saving (D7).** `mark_saved()` is the hook W5's steps call once they write. From then
  Discard dungeon is offered: it asks first, then moves the dungeon's folder to
  `_archive/<slug>-<stamp>` beside it (going back to the blank map if it was showing).
  Cancel after a save says "Continue with Dungeon → Floors… → Add."; before one, that
  nothing was saved.
- **Players held (D6).** While the wizard is open a player's view is the empty envelope
  plus `"hold": "The DM is preparing the dungeon…"` (`net.view._hold_view`); the event
  filter shows them nobody, and `MapImageCache.hold_players` makes `GET /map.png` 404 for
  them. The client shows the text over the empty board. The DM's view is unchanged.
- **Left in place:** the old New Dungeon dialog functions (`dungeon_new`,
  `open_campaign_new_dungeon`, `new_dungeon_from_scene`, …) and `on_generate_dungeon` are
  no longer reachable from a menu; their suites still drive them directly. They go when
  W5/W8 have replaced what they did (the "this map" import of a loose scene into a
  campaign has no wizard equivalent yet).
- Tests: `tests/test_dungeon_wizard.py` (9 cases, real clicks/keys through
  `_handle_events`); `test_gameview.py` gains `test_held_while_the_dm_builds_a_dungeon`;
  `test_dungeon_menu.py` and `test_new_dungeon_dialog.py` updated for the new entry points.

### W5 as built (2026-11-23)
- **Steps.** Premade maps → 2. Pick an image (From a file… / From the campaign library…,
  sources listed first / a sheet already picked this run) → 3. Set Grid → 4. Crop a floor →
  5. Name the floor → 6. Another floor? (Another floor from this sheet: straight to Crop,
  grid kept; Another image: back to Pick; **Finish** opens the dungeon on its entry floor).
- **The working area** (`gui/sheet_canvas.py`): from Set Grid on, the sheet is drawn over
  the map view, never loaded into the engine. Wheel zooms, right/middle-drag pans,
  arrows / + / − / 0 as on the map. Big sheets scale only the visible part, from a
  ≤ 2048 px preview when zoomed out. The scene underneath is untouched.
- **Set Grid (D13).** Drag a box over whole squares, set Across / Down (how many squares it
  covers) and 5 ft / 10 ft / Other. The square is a float (box ÷ squares), so a big sheet
  doesn't drift; the sheet's `manual_grid` gets the whole-pixel cell, and the source block
  gains an optional **`"square_px"`** (W1 amended: `SourceSheet.square_px`). The default
  square size is the last sheet's. A **library map that already has a grid keeps it**
  (other dungeons may read that `map.json`): Set Grid shows it and Next goes on; the map
  is only marked as a source.
- **Crop (D14).** A drag snaps to the nearest drawn grid lines inside the sheet; **Whole
  image** is every whole square. The brush (Off / Paint / Erase) blackens whole drawn
  squares inside the crop. Floors already cut from the sheet are outlined on it.
- **Size (D15).** The sheet's resolution, rounded to a **whole number of pixels per 5-ft
  cell**, so every floor's grid is `{"cell_px": c, "anchor": [0, 0]}` and sits on the
  drawn lines; shrunk when the longest side is over 2048. `crop.scale` records it.
- **Name (D16).** Default `<dungeon>-floor-<N>`, N from 1. Refused when the campaign
  library (or, loose, the dungeon's folder) already has that name.
- **Saving (D7, D9).** Naming a floor writes it, and the dungeon around it is whole and
  openable from then on (Discard is offered from the first floor). A picked sheet is
  copied in when its **first floor is written**, not on pick, so Cancel before any floor
  still leaves nothing. Campaign: sheet and floors are library maps (`maps/<name>/`, image
  + `map.json` with grid and crop), plus `dungeon.json`, `runs/main/run.json` and
  `session.json`; loose: `maps/<dungeon>/` holds the sheet (in the manifest's `sources`),
  each floor's `.png` / `_terrain.json` / `_agents.json` and the version-1 manifest.
- **Back (D7).** Reopens an earlier step for the floor it was about: a re-crop overwrites
  that floor's image and design and keeps its place; a new name renames it (library
  folder, page, entry, run section). Once a floor is written Back stops at Pick an image
  (the first screen's answers are fixed).
- **Discard** now also archives the campaign library folders this run made (floors,
  copied sheets) under `_archive/<slug>-<stamp>/library/`.
- **Placement, interim until W6:** each later floor goes one floor above the highest, at
  the same corner as the floor written before it (D19's Skip).
- `main.py`: the file browser takes events ahead of the wizard while it is open.
- Code: `gui/wizard_floors.py` (geometry + `FloorWriter`), `gui/sheet_canvas.py`,
  `gui/dungeon_wizard.py` (steps). Tests: `tests/test_wizard_floors.py` (6 cases, new);
  `tests/test_dungeon_wizard.py` +2 (loose click-through with real drags; campaign +
  Discard). Headless screenshots of Ravenloft's spires sheet checked by eye.
- **D15 amended (user, 2026-11-23): a minimum of 6 px per 5-ft cell** (`MIN_CELL`). A
  sheet with smaller cells is enlarged to 6; the 2048 px cap still wins over it. The
  spires sheet (5.6 px a cell) rounds to 6 either way; W2's existing crops are at 16.

### W6 as built (2026-11-23)
- **Steps.** Name → (first floor: straight to Another floor?, D17) → **6. Place the floor**
  → **7. Align the floor** → 8. Another floor?. Back walks them in reverse; a floor is
  first written one floor above the highest (as in W5), and Place moves it.
- **Place (D18).** Above / Below / Beside chips, and Against: every other floor (page) of
  the dungeon, top first, defaulting to the floor written before. The panel shows **the
  stack** as it would be (entry ★, "← new"); the map view previews it. Next saves.
- **Z rules** (`gui/floor_place.py`, settled here): the entry's Z never moves. A level
  taken where the floor goes gets a new level inserted, shifting the block of floors on
  the side away from the entry; a floor leaving a level it held alone closes the gap, so
  the stack stays contiguous. Ladder / door-staple targets (`[X, Y, Z]`) move with their
  floor; staircases are page-local and need nothing.
- **Align (D19)** (`gui/align_canvas.py`): floors drawn at their global cells by their
  manual grid; the floor being placed opaque (gold), the floor it sits on / under faded
  over it (blue); beside: the other maps of its floor faded, the floor below faint.
  Click a landmark on the new floor, then the same point on the faded floor: the floor
  moves to the nearest cell. Arrows move it a cell, Enter accepts (saves). **Skip** saves
  the default corner: the reference floor's corner above / below, just east of that
  floor's pages beside. Right-drag pans, wheel / + / − zoom, 0 fits.
- `FloorWriter` gains `manifest` / `load_dungeon` / `save_dungeon` / `page_art`.
- Tests: `tests/test_floor_place.py` (5 cases, new); `test_dungeon_wizard.py` +1
  (place below, landmark clicks on the canvas, nudge, beside + Skip) and the W5
  click-through updated for the new steps. Headless screenshots on the spires sheet
  checked (`tools/debug/w6_shots.py`, untracked).

### W7 as built (2026-11-23)
- `gui/floor_checklist.py`: `FloorChecklist` (`app.floor_checklist`), docked over the right
  panel like the wizard, the map live beside it. One block per floor (page), top floor
  first, manifest order within a level: `★ name · floor Z`, then six chips
  Grid ✓/✗ · Aligned ✓/✗/?/Entry · Walls: none/detected/edited · Doors N · Stairs N ·
  Creatures N, green when done, amber when not. Wheel scrolls; Esc / Close shut it.
  Buttons Overview… and Add… (the old Floors… entries, D2).
- **Opens** from Dungeon → Floors… (`menus/dm.show_floors_menu`, no longer a popup) and
  after the wizard's Finish.
- **Where the numbers come from:** the floor showing is read from the live scene (unsaved
  edits count); the others from the store (`store.terrain` / `store.creatures`), so it
  works for campaign and loose dungeons. Nothing is written. Grid: a `manual_grid`, or a
  page with cols × rows. Walls (`walls_state`): OFF with nothing painted = none; ON with
  edge overrides or painted Wall regions (or OFF with painted walls) = edited; else
  detected. Staircases: ends on that page. Creatures: every record on the map.
- **Aligned, settled here (W1 amended, D26):** a page gains an optional `"aligned"` bool
  in both manifest shapes (`MapPage.aligned`). The wizard writes a later floor `false`,
  Place resets it to `false`, Align's accept sets `true`, Skip `false`; Align Floor's
  Enter sets `true`. Absent (`None`) shows "Aligned ?" (pages made before W7, e.g.
  Argynvostholt, Ravenloft); the entry shows "Entry".
- **Jumps** (`jump`): switch to the floor (refused in combat, as any switch), then
  Grid → Set Grid's tile drag; Aligned → Align Floor; Walls → Wall Detection (walls OFF:
  turned ON first, through the overwrite confirm), or, once edited, the terrain editor's
  Edge tool (Drawn mode) / Wall tool; Doors → editor, Door tool; Stairs → editor,
  Staircase tool; Creatures → Populate Floor….
- Tests: `tests/test_floor_checklist.py` (5 cases, new); `test_dungeon_menu.py` (Floors…
  opens the checklist); `test_dungeon_wizard.py` (Finish shows it; aligned recorded
  for landmark vs Skip). Headless screenshot on a copy of Argynvostholt checked
  (`tools/debug/w7_shot.py`, untracked).

### W8 as built (2026-11-23)
- **Floors… → Add…** (the checklist's Add button) opens the wizard in an add mode,
  `DungeonWizard.start_add(app)`, on the open dungeon (`target_for_open_dungeon`: a
  campaign dungeon by its folder; a loose one by its manifest, wherever it is). Refused
  in combat. Header "Add a floor — …"; it starts at Pick an image (Back stops there).
- **Kept sheets (D12)** (`wizard_floors.kept_sheets`): campaign, the library maps the
  dungeon's floors' `crop` blocks name; loose, the manifest's `sources`
  (`sheet_from_loose_source`, already placed, its grid from its `_terrain.json`). They are
  listed under "Sheets" with their grids, so picking one goes straight through Set Grid.
- Every added floor is placed and aligned (no D17 shortcut); Place defaults to the floor
  showing when Add began. Names default to `<dungeon>-floor-<N>` past the existing pages,
  and an existing page's name is refused.
- **Saving.** Add saves the scene first. The writer then writes to disk, so the app's copy
  of the dungeon (and a campaign's run) is stale: Finish, or Cancel after a floor is
  written, **reopens the dungeon from disk** without saving over it, back on the floor that
  was showing; Finish then shows the checklist. Discard is never offered in add mode.
- **Removed:** Add Page's `dungeon_add_page_browser` / `on_add_page_png_chosen` and their
  `main.py` wrappers (the v1/v2 Add Page path); nothing else called them.
- **Not in W8:** re-cropping an existing floor in place from its sheet (D7's Back covers
  it only inside a wizard run).
- Tests: `test_dungeon_wizard.py` +2 (loose Add from the kept sheet through the checklist's
  button, taken name refused, place below + align, Finish; campaign Add from a new file,
  combat refusal, Cancel reopens and a later save keeps the floor in the run);
  `test_floor_checklist.py` Add button updated.

### D25 commands (for the user to run; Claude never runs `rm -rf`)
```bash
cd ~/Claude/DND/encounters
tar czf ../random_encounters_backup.tgz random_encounters
rm -rf random_encounters/bad-pixies random_encounters/test random_encounters/_archive
```
