# QOL — Quality-of-Life Improvements

Running list from live play (started 2026-10-21). Items are observations from the DM
(noVNC, :6080) and player (Battle Map, :6081) screens.

Format: **[DM|Player|Both]** short title — what happened, what would be better.

## Open

- **[DM] Terrain editor zoom/pan doesn't match the main map view** (2026-10-22) — While
  walling the Castle Ravenloft spire floors, the terrain editor's zoom and pan controls
  behave differently from the main DM screen (the map view with the − / % / + / Fit bar).
  They should be the same: same inputs, same zoom range and readout, and the editor
  should open at the main view's current zoom/pan (and hand it back on close).

- **[DM] Don't re-run wall detection every time a floor loads** (2026-10-22) — Paging
  between dungeon floors calls `_load_map_png` → `bm.detect_walls()` (and
  `_redetect_walls` after the terrain loads), so every page's walls are rebuilt from its
  image each time. Once the DM has walled a floor by hand, that result should be
  fixed: save the resolved walls in the page's `_terrain.json` (static edge walls via
  `bm.edge_walls`, plus the blocked/disallowed cell set) and load them back instead of
  detecting. Detection runs only when the DM asks for it (Wall Detection…, Set Grid…,
  Rescale) or the page has never been walled. Needs a binding to set disallowed cells
  (today there is only `allow_cell`). Found while padding the Castle Ravenloft pages to one
  frame: new padding was re-detected as blocked on the next load.

## Bugs

- **[Player] Attack button needs 2–3 clicks to register** — On the player screen, clicking
  "Attack" during Ireena Kolyana's turn (adjacent to Strahd) often does nothing the first
  time; it takes two or three clicks before the attack actually arms/registers. Suspects:
  the click racing a live-state re-render that rebuilds the action bar (button replaced
  between mousedown and click), or the request being dropped/debounced server-side.

## Done

- **[Player] No zoom on the player screen** — QOL_PLAN Q1 (2026-10-21): wheel/trackpad,
  pinch, drag-to-pan, + / − / Fit and a % readout; range 50–600% like the DM. Checked live.
- **[Both] Homogenize layout / map zoom across DM and player screens** — QOL_PLAN Q2
  (2026-10-21): from 56rem up, the player page uses the DM's layout — board fills the left
  at full height, a 340 px right column (`constants.PANEL_W`) holds the prompt and panels.
  Phones keep the stack. Checked live.
- **[Player] Merge initiative and health into one table** — QOL_PLAN Q3 (2026-10-21): one
  table in initiative order (▶ · name · init · HP · conditions), the rest of the board below
  a divider; alphabetical out of combat. Checked live.
- **[Player] Show whose turn it is the way the DM screen does** — QOL_PLAN Q3 (2026-10-21):
  the DM's gold ▶ row and the yellow outline on the token on turn. Checked live.
- **[Player] Match the DM's action-panel groupings** — QOL_PLAN Q4 (2026-10-21): the offer
  carries each row's DM section and button colour, in the DM panel's draw order; the
  player screen draws Action / Bonus Action / Movement / Other / End Turn in those colours,
  with disabled rows greyed and their reason shown. Checked live.
- **[Player] Drag-to-move preview like the DM screen** — QOL_PLAN Q5 (2026-10-21): no Move
  button; pressing your token opens Move and paints the reachable squares, the DM's ghost
  follows the pointer with a green/red outline, a drop on green moves, and your own move lands
  without replaying. Checked live.
