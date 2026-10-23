# Staircases

**Status 2026-10-22: Step 0 frozen (D1–D6 decided). Steps 1–3 done; step 4 converted (37 staircases) and labelled.** Came out of laddering
Castle Ravenloft: every stair there is faked with ladder pairs, and the pairs keep colliding.

## Status and handoff (2026-10-22)

- **Step 0:** frozen; D1–D6 decided (below).
- **Step 1 (manifest): done.** `gui/dungeon.py` has `StaircaseEnd` / `Staircase` and, on
  `Dungeon`: `staircases`, `next_staircase_id`, `new_staircase(page, cell)` (end A,
  unfinished), `finish_staircase(id, page, cell)` (end B; ValueError unless Z ± 1),
  `remove_staircase(id)`, `staircase_by_id`, `staircase_ends_on(page)`,
  `staircase_ends_at(page, cell)`, `staircase_direction(st, end_index)` → "up" / "down" /
  None (unfinished or broken), `staircase_end_global(end)`. `remove_page` unfinishes or
  drops staircases. Keys are written only once a dungeon has had a staircase.
  Tests: `tests/test_staircases.py` (10), registered in `run_all_tests.py`; suite 191/0.
- **Step 2 (use + players): done.** `gui/main.py`: `_staircase_ends_here`,
  `_staircases_at(cell)`, `_staircase_option_label`, `_use_staircase(sid, end, actor)`
  (through `_switch_to_page`, so refused in combat), `_staircase_cells_here` (fog as for
  ladders), `_draw_staircases`, `_draw_staircase_hover`; the map click opens
  `dm.show_staircase_menu` after the ladder check. Glyph: `draw_stair_glyph` in
  `terrain_dialogs.py` (for the editor too). `net/view.py` sends `terrain.staircases`
  (`id`, `name`, `cell`, `direction`; DM also gets `label`, `target_page`).
  **Player submit** is the ladder's: the menu is an `_ask_actor` prompt owned by the
  creature's controller, so the bus authorizes the answer. A player cannot *open* it
  from the browser; that waits on MULTIPLAYER M5f (Interact), as for ladders and doors.
  Tests: `tests/test_staircase_use.py` (5); suite 192/0.
- **Step 3 (editor): done.** `gui/terrain_dialogs.py`: tool **[9] Staircase**. A click
  places end A of a new staircase, or end B of the one picked to finish (the editor opens
  offering the newest unfinished staircase one floor away; **[F]** cycles new / each
  unfinished one, and a non-adjacent floor is refused with a reason). A click on an end
  selects it (again: the next one on a shared cell); **Shift+click** places on an end
  (D2). With an end selected: **[M]** move, **[N]** rename, **[L]** label (empty clears),
  **[Del]** delete the staircase. **Ctrl+Z** undoes staircase edits (own stack; the id
  counter is never rolled back). Rename/label use `app.name_prompt` (`allow_empty` added),
  which the event loop now routes *above* the terrain editor. `main.py`:
  `_close_terrain_editor` writes the manifest (`_dungeon_save_manifest`) when the
  staircases changed. **Staircases…** in Dungeon Configuration (`dm.show_staircases_menu`):
  one row per staircase (`_staircase_summary`), each opening Go to end A / B
  (`_staircase_goto`, refused in combat), Rename…, Relabel…, Delete; every change writes
  the manifest. Tests: `tests/test_staircase_editor.py` (7); suite 193/0.
- **Step 4 (Ravenloft conversion): converted; labels still to fill in by hand.**
  `tools/ladders_to_staircases.py <manifest> [--keep PAGE:COL,ROW ...] [--apply]`: pairs
  every ladder with its return (the ladder on its landing that leads back onto one of its
  cells), lower floor as end A, ids in floor order; reports and stops on an unpaired,
  ambiguous or non-adjacent ladder and on a `--keep` that names none; a same-page ladder
  is left alone. Dry run by default; `--apply` backs up to `pre_staircases/`. Run on
  Castle Ravenloft 2026-10-22 with `--keep tower_peaks_map9_10_ravenloft:39,20` (K60 →
  roof): 74 ladders → Staircases 1–37, 2 ladders left. Tests:
  `tests/test_ladders_to_staircases.py` (7); suite 194/0.
- **Labels: done 2026-10-22** (written straight into the manifest; snapshot before in
  `encounters/Castle Ravenloft/staircases_v1/`). K21: 4 9 16 24 27 30 34 (34 = K21/K57) ·
  K18: 5 10 17 26 29 32 35 37 (37 = K18 to K59) · K20: 18 25 28 31 33 36 (36 = K20 to K60) ·
  K83: 2 6 13 22 · K64: 7 15 23 · 1 K79/K72 · 3 north stair · 8 K20a · 11 K63/K23 ·
  12/14 side stair W/E · 19 K24 · 20 east stair · 21 K13.
- **Helix pass: done 2026-10-23** (supersedes the shared-landing pass, which the user
  rejected: a spiral can't go up and down from one square). Snapshot before: `staircases_v3/`.
  Each spiral is a screw: a staircase's two ends are the **same (c, r)** on both floors, and
  on each floor the arriving and leaving ends sit on **opposite treads**, alternating floor
  by floor. Handedness read from the drawings (on screen, y down): K18, K21, K64 climb
  counter-clockwise; K20, K83 clockwise (the user's "K18/K21 clockwise, K20 counter" is the
  same thing mirrored). Squares: K18 W (39,31) / E (44,32); K21 (37,33) / (34,34), then
  K47 up (36,29), K48→K57 (35,31); K20 E (41,18–19) / W (31,19), K60 arrives W (32,20);
  K64 (32,36) / (31,39); K83 Z−2 top E (25,18), then (25,22) / (22,22), Map 5 arrives E at
  the door. K23 (11, 20) back on its two flights. No square holds two ends.
  Close-ups: `.tmp_claude/ravenloft/helix/new_<stair>.png`.
- **User offsets applied 2026-10-23 09:15** (snapshot before: `staircases_v4/`). Ends of a
  helix need not stack: they sit at different heights on the spiral, so a staircase's two
  ends may have different (c, r). Staircase 3 deleted (36 left; ids 1–2, 4–37). The Z+6
  K60 → roof ladder removed; staircase 36 now ends there at (39,20). The roof's ladder was
  removed too (2026-10-23 09:25): Ravenloft has no ladders now and no way onto the roof.
- **Next:** the user checks it in the game.

## Decided (user, 2026-10-22)

- **Stairs are portals, separate from ladders.**
- **Each staircase has a unique id:** "Staircase 1", "Staircase 2", and so on.
- **A staircase links one floor to the next, and its far end can be anywhere on that floor.**
  No same-X, Y rule and no helix geometry. A spiral's landings are wherever the DM puts them.

## Why ladders don't work for stairs

A **ladder** today is a per-page record, `{"cells": [[c, r]], "target": [X, Y, Z]}`. Its two
ends are linked only by coordinates. The terrain editor writes the return end **directly
above or below** and refuses it if that cell already holds a ladder. On a spiral the up and
down ends on one floor sit on neighbouring cells, so the vertical return keeps landing on
the wrong ladder. Most of this session's one-way fixes were that collision.

A **staircase** is one record that owns both ends. The ends are linked by its id, so:

- they can be anywhere on their two floors;
- two staircases can have ends on neighbouring cells, or even the same cell (D2), with no
  interference;
- deleting a staircase deletes both ends, so it can't become one-way.

## The model

Staircases live in the dungeon manifest, because each one spans two pages:

```json
"staircases": [
  {"id": 1, "name": "Staircase 1", "label": "K21 Catacombs → Larders",
   "ends": [{"page": "dungeons_and_catacombs", "cell": [24, 34]},
            {"page": "larders_of_ill_omen",    "cell": [22, 27]}]},
  {"id": 2, "name": "Staircase 2", "label": "K21 Larders → Main",
   "ends": [{"page": "larders_of_ill_omen", "cell": [22, 28]},
            {"page": "main_floor",          "cell": [37, 31]}]}
]
```

- `id`: integer, unique in the dungeon, never reused after a delete. `name` defaults to
  "Staircase {id}", and the DM can rename it. `label` is an optional note (the book key).
- `ends`: two **page-local** ends `{"page": id, "cell": [c, r]}` (D5), on pages whose Zs
  differ by exactly 1 (D1). The global cell is derived (`page.local_to_global`), never stored,
  so moving a page on its floor doesn't break its ends, and a grid rescale
  (`grid_rescale.py`) keeps every cell index, so it needs no remap.
- While being placed, a staircase may have one end only (`"ends": [A]`, D6). It is listed
  as unfinished and cannot be used.
- A page finds its staircase ends by filtering `staircases` for its page id. Nothing is
  written into the page's `_terrain.json`.
- The manifest is written when the terrain editor closes and on every change from the
  Staircases… list. Editor undo covers staircase edits.

## Using a staircase

- Click an end, or select a creature standing on or next to it. The menu offers
  **Ascend** or **Descend**, by which way the other end lies: "Ascend Staircase 7 (K21) to
  Court of the Count" / "Descend Staircase 7 (K21) to Larders". A shared cell (D2) offers
  both.
- The creature is carried to the other end through the existing
  `_switch_to_page(page, drop_cell, carry)`, the same as `_use_ladder`.
- The end is drawn with its own marker, not the ladder's: a stair glyph with the id and an
  ↑/↓ arrow. Hovering shows the name, label and destination floor.
- **Player screens:** staircase ends go into the player view (`net/view.py`, beside
  ladders) under the same fog rule as ladders, and a player can submit Ascend / Descend
  for their own creature, validated server-side the same way as a ladder climb.

## Editor

A **Staircase** tool in the terrain editor, next to Ladder:

Two-phase placement (D6), so the editor never switches pages mid-session:

1. Click a cell on this floor to place end A. This creates an **unfinished** staircase with
   the next id, saved in the manifest when the editor closes.
2. The DM leaves the editor and switches to the floor above or below the normal way (floor
   overlay available).
3. Opening the editor there offers "Finish Staircase 7"; the DM clicks end B. It is
   refused unless the page's Z is A's Z ± 1.
4. Click an existing end to rename or relabel it, move that end, or delete the staircase.

A **Staircases…** list in Dungeon Configuration shows every staircase: id, name, label,
both ends, and whether it is unfinished. From it you can jump to either end, delete, or
relabel.

## Decisions (decided 2026-10-22)

- **D1: Floor gap.** Each staircase joins adjacent floors only (Z and Z ± 1). A tall stair
  like K21 is then a chain of staircases. **Decided:** yes.
- **D2: Shared cells.** May a cell hold the end of two staircases (a spiral's landing that
  goes both up and down)? **Decided:** yes; the menu offers both Ascend and Descend.
- **D3: Combat.** Page changes are refused in combat (one page simulated).
  **Decided:** refused, the same as ladders, until cross-page combat exists.
- **D4: Party travel.** Only the acting creature crosses, as with ladders.
  **Decided:** yes for now; "bring adjacent allies" is a separate item for both.
- **D5: Page-local ends.** Ends are `{page, cell}`, not global `[X, Y, Z]`. **Decided:** yes.
- **D6: Two-phase editor.** End A, then end B from the other floor's editor session; an
  unfinished staircase persists in between. **Decided:** yes.

## Castle Ravenloft migration

Every ladder pair placed today, except real ladders, becomes one staircase. Its two ends
are the pair's two cells, so nothing moves:

| Staircase chain | Floors | Ladder pairs → staircases |
|---|---|---|
| K21 | −2 → +5 | 7 |
| K83 | −2 → +2 | 4 |
| K64 | −1 → +2 | 3 |
| K18 | −2 → +6 (K59) | 8 |
| K20 | 0 → +6 (K60) | 6 |
| K8/K13 grand stair, K13, K79/K72, K63/K23, north stair, K24, side stairs | various | ~9 |

**Stays a ladder:** K60 → roof. (K34 → K20 is on one page; out of scope.)

The conversion is a one-off script: read every page's ladders, match each with its return,
write one staircase per pair as "Staircase N" with no label, then delete those ladders.
It prints the pairs; labels (K21, K83, …) are filled in by hand from the table above.
A ladder with no return partner is an error the script reports and stops on; it does not
guess. It is checked by: the same 37-or-so links exist before and after, and no ladder is
left except the real ones.

## Steps

Each step lands with its own tests (container, `./test.sh`).

1. **Manifest:** `staircases` read and written by `gui/dungeon.py`, page-local ends; the
   next id never reuses a deleted one (a stored `next_staircase_id`, not `max(id) + 1`).
   Old manifests load unchanged; page removal drops or unfinishes its staircases. Grid
   rescale needs nothing: `grid_rescale.py` keeps every cell index, so page-local ends
   stay put. *Tests:* round-trip, unique ids not reused after delete, old manifests load.
   **Done 2026-10-22** (`tests/test_staircases.py`, 10 tests; suite 191/0).
2. **Use:** end lookup per page, the Ascend / Descend menu, the transition through
   `_switch_to_page`, the marker, refusal in combat; player view + player submit.
   *Tests:* carries a creature both ways; neighbouring and shared ends don't interfere;
   refused in combat; unfinished is unusable; player view lists ends under fog; player
   submit validated.
   **Done 2026-10-22** (`tests/test_staircase_use.py`, 5 tests; suite 192/0).
3. **Editor:** the Staircase tool (two-phase), undo, the Staircases… list. *Tests:*
   place A, finish B on Z ± 1 (refused otherwise), delete removes both ends, edit/undo.
   **Done 2026-10-22** (`tests/test_staircase_editor.py`, 7 tests; suite 193/0).
4. **Ravenloft:** run the conversion, then label by hand. *Tests:* the conversion keeps
   every link; an unpaired ladder stops it.
   **Converted 2026-10-22** (`tools/ladders_to_staircases.py`,
   `tests/test_ladders_to_staircases.py`, 7 tests; suite 194/0); labels pending.
