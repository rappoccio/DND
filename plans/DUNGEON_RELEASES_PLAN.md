# Dungeon releases, Reset Dungeon, Load Save File

**Status 2026-11-06: complete. Step 0 frozen (D1–D10), steps 1–7 done.** These decisions change
only by a dated amendment with a reason, agreed with the user.

Builds on `plans/SAVE_LAYOUT_PLAN.md` (a dungeon's design is `dungeon.json` + `maps/`, play
state is `runs/<run>/run.json`). `CampaignStore` already keeps the two apart, which is what
makes these features cheap.

## Model

- **Release**: a numbered, read-only snapshot of a dungeon: its design plus a starting board.
- **Reset Dungeon**: put the run back to a release's starting board. Design stays current.
- **Save file**: one point in a run, stamped with round, actor and time. Load restores it
  the way Restore Autosave does, from any turn.

```
<dungeon>/
  releases/V0/
    release.json        name, note, timestamp, current_map
    dungeon.json        copy
    maps/               copy: map.json, lighting.json, encounters, local images
    start/run.json      the board at release time, PCs included
    start/effects/
  runs/main/
    saves/
      index.jsonl       one line per save: file, kind, fight, round, actor, map, time
      <seq>.save.json.gz
```

## Step 0: decisions (to freeze)

The user's calls (2026-11-06): D1, D3, D5, D8.

- **D1. A release is design + current board.** It holds everything in the layout above, with
  PCs as they stand when it is made. Library art is referenced, not copied, because nothing
  inside a dungeon changes the library (SAVE_LAYOUT D3). A `map.json` or `lighting.json`
  that resolves to the library is copied in, so the release is complete.
- **D2. Making a release.** One click names it the next `V<n>`, starting at `V0`. It saves
  the live scene first and is refused during combat. Written to a temp folder, then
  renamed, so a crash cannot leave half a release. Never overwritten; the app has no delete.
- **D3. Reset restores play state only.** `run.json` and the run's effects come from the
  release; `map.json`, `dungeon.json` and encounters are not touched, so a wall fix survives
  a reset. Doors keep their current design and take the release's state by door key
  (`merge_terrain`). A map added since the release starts empty.
- **D4. Reset behaviour.** One confirm, naming the release. The default is the newest, and a
  `Releases…` list can reset to an older one. It works mid-fight and ends the fight, but is
  refused when `autosave.restore_blocked` objects. It writes a `before reset` save first, so
  an accidental reset can be undone through Load Save File. With no release yet, it says
  "Make a Release first". Seats stay and players get a fresh view (as `_resync_players`).
- **D5. Save files come from every turn and from a Save Game action.** Every turn start
  writes one, at the same point as the autosave and under the same `RPG_AUTOSAVE` switch.
  Save Game works in or out of combat. The autosave ring and its menu stay as they are.
- **D6. A save holds the whole run.** `run.json` (every map), the current map's raw creature
  list, the fight (`_save_combat_state`) and effects. One gzip file per save, written
  atomically, about 100 KB on today's dungeons. `index.jsonl` is only a cache, rebuilt from
  the files if it is lost.
- **D7. Loading a save** works like restore: same refusals and the same `_settle_turn` /
  `_resync_players`, and it never re-points anything. It also switches to the save's map
  (without writing the outgoing scene back) and ends any live fight if the save has none.
  **It does not load saved terrain**: the scene comes from the current design plus the saved
  state, per D3, and never writes `map.json` or `dungeon.json`.
- **D8. Retention is configurable; the default is 10.** Keep the newest `save_limit` turn
  saves per run; the oldest is dropped when a new one is written. `save_limit` is stored in
  the campaign's `session.json` beside `autosave_slots` and clamped to at least 1. The Table
  menu has a `Save limit: <n> ▸` row (10, 25, 50, 100, 500, 1000); lowering it prunes on the
  next write. Manual and `before reset` saves are never dropped and do not count.
- **D9. The picker is a cascading menu.** Manual saves first, then fights, newest first:
  `Nov 6 14:02 · 12 turns ▸` → `Round 3 ▸` → `Goblin Minion · 14:09:31`. A fight is one
  Begin Combat. Table's session log names only the round, never the actor, as restore does
  (D-M7-4).
- **D10. Campaign dungeons only.** A loose map or a version 1 dungeon has no run to reset, so
  these actions say so. Its autosave ring is unchanged.

**Buttons:** the setup panel gets `Reset Dungeon` and `Load Save File…`. The Dungeon menu gets
`Release`, `Releases…` and `Save Game`. The Table menu, which works mid-fight, gets
`Save Game`, `Load Save File…`, `Reset Dungeon` and `Save limit`.

**Not in this plan:** rolling a dungeon's *design* back to a release. The snapshot makes it
possible later, but a release's design is read-only history for now.

## Known risks

- **A wall fix can land on a released creature's cell.** The open SAVE_LAYOUT issue applies:
  a creature on a blocked cell is skipped on load and dropped by the next save. Step 3
  reports any such creature by name on reset. The release itself still has it.

## Steps

Each ends with its suite green in the container and is committed on request.

1. Restore Autosave's map-fix bug: failing test, then the fix. **Done:** in a campaign a
   slot now gives only fog and door state (`CampaignStore.adopt_play_state`).
   `tests/test_autosave_design.py`.
2. `gui/releases.py`: create, list and read a release, with no UI. `tests/test_releases.py`.
   **Done.** On copies, Ravenloft's release is 8.1 MB and takes 32 ms.
3. Reset Dungeon: the run swap, the page reload, the fight ending, the seat resync and
   confirm. Dungeon menu rows for `Release` and `Reset Dungeon`. **Done:** `gui/run_control.py`,
   `tests/test_dungeon_reset.py`. A creature blocked by a map fix is named for the map shown;
   another map's is found when that map is next opened.
4. `gui/saves.py`: write, index, prune and load, then the turn hook and `Save Game`.
   `tests/test_saves.py`, including a save on another map and a fight resumed after a wall
   fix. Measure the turn hook's cost on Ravenloft. **Done:** `run_state.keep_current_design`
   rests a resumed fight on today's walls and lighting, for autosave restores too. A turn save
   on Nedragaard Keep's 32-creature fight takes about 50 ms and 68 KB. (Ravenloft's current map
   would not start a fight headless, so its 11–18 ms is out of combat.)
5. The cascading picker and `before reset` wired into D4. **Done:** `dm.show_load_save_menu`.
   A reset that cannot write its before-reset save does not happen.
6. Panel buttons and Table rows; check the layout with `tests/gui_driver.py` screenshots.
   **Done.** `Save limit` is on the Table menu.
7. Register the suites, update docs, run the whole suite. **Done.** Release, reset and undo
   checked end to end on copies of all four real dungeons; map.json never changed.

## Open after this plan

- **A release cannot bring back a creature already lost.** The SAVE_LAYOUT issue applies when
  a release saves the board: Church of St Andral loads without Aodhan and Ireena Kolyana (their
  cells are blocked), so a release made there leaves them out too, and the save drops them
  from the run. Fix that issue, or move them, before releasing that dungeon.
- A reset waits while a reaction prompt or the legendary-action phase is open (D4).
