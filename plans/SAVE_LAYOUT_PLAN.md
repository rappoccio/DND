# Save layout: campaigns, maps, encounters, PCs

**Status 2026-11-05: Step 0 frozen (D1–D12). Step 1 done (uncommitted, 211/0); step 2 next.** Came out of the Sithicus folder: seven
copies of one map's terrain, names compounding (`_dungeon_dungeon_dungeon_agents.json`),
and edge doors "missing" from generated encounters.

## Why

Every file today is keyed by the *agents file's* name (`_sidecar_base`, `main.py:2374`):
terrain, lighting, effects, combat, session and the autosave ring all follow it. So:

- **Every encounter carries a full copy of the map.** Grid, detection, edge overrides and
  doors are map facts, but each encounter has its own ~300 KB `_terrain.json`, and the
  copies drift.
- **Names compound.** Single-map Generate Dungeon writes `<current base>_dungeon_agents.json`
  (`_dungeon_out_path`, `main.py:13986`); generating again from that gives
  `_dungeon_dungeon`. Save As takes whatever is typed (`_pc`, `_pcagents`, `_pc_dungeon`).
- **The edge-door loss.** Generate Dungeon saves terrain to the *old* base, re-points the
  encounter at the new one, and never writes the new `_terrain.json`
  (`main.py:14403–14422`). Until something saves, the generated encounter has no terrain
  file; loading it then gives no doors, grid, edge walls or fog. Sithicus timestamps fit
  (`_dungeon_agents` 10:29, `_dungeon_terrain` 10:33). Not fixed separately: one shared
  `map.json` removes it.
- Also seen: an autosave ring nested inside a slot (`…_autosave/slot_0/…_autosave/…`,
  Nov 4, before or despite the M6.4 guard) and a roster that stacked to 44 agents
  (`_pc_dungeon_agents.json`: 19 Pixies, duplicate Sabalath).

## Model

```
campaign ─┬─ pcs                 the party, one file per character
          ├─ maps                the art library (originals)
          └─ dungeons ─┬─ maps         N maps, each a library map (or a local override)
                       │    └─ encounters   M per map: named creature groups
                       └─ runs         the party's traversal: live state of every map
```

A single map is a dungeon with one map. Players traverse a dungeon; a run is that
traversal saved.

## Target layout

```
encounters/
  Curse of Strahd/                       campaign
    campaign.json                        marker + metadata (name, version)
    session.json                         join code, seats, autosave_slots
    pcs/
      aodhan.json                        one PC per file
    maps/                                library: original art, shared by dungeons
      main-floor/
        main-floor.png
        map.json                         (optional) calibration/walls/doors for this art
        lighting.json                    (optional)
    castle-ravenloft/                    dungeon
      dungeon.json                       maps [{id, map, origin, cols, rows}], entry map,
                                         staircases, ladders, door staples, room labels
      maps/
        main-floor/                      local override, checked first (D3)
          main-floor.png                 e.g. the framed / rescaled-to-grid copy
          map.json                       grid, detection, walls_enabled, edge overrides,
                                         regions, doors (where, lock/DC defaults)
          lighting.json
          encounters/
            k10-dining-hall.json         creatures + map items + conditions,
                                         on_deck per creature, generator meta
      runs/
        main/                            the default run
          run.json                       every map's creatures (PCs included), fog,
                                         door open/broken/locked, effects, current map
          combat.json                    mid-combat resume (only while a fight runs)
          autosave/slot_<k>/
    church-of-st-andral/                 a one-map dungeon
      ...
```

## Step 0 — decisions (to freeze)

- **D1. Campaign is the root.** A directory with `campaign.json`. The app always runs
  inside one; the campaign is found by walking up from whatever was opened.
- **D2. Map library.** `<campaign>/maps/<map>/` holds original art plus optional
  `map.json` / `lighting.json`. Importing an image outside the campaign copies it here.
- **D3. Child-first resolution, copy-on-write.** For each of a dungeon map's files (image,
  `map.json`, `lighting.json`) the app uses `<dungeon>/maps/<map>/<file>` if present, else
  `<campaign>/maps/<map>/<file>`. Edits are always written to the dungeon copy, so the
  library never changes from inside a dungeon. A rescale-to-grid writes the new image
  into the dungeon copy. The image and `map.json` should come from the same level (a grid
  calibrated for one image is wrong for a rescaled one): an override image without its
  own `map.json` is a warning.
- **D4. Dungeon.** `<campaign>/<dungeon>/dungeon.json` replaces `.dungeon.json`: maps,
  global origins, staircases, ladders, door staples, room labels, entry map. A one-map
  dungeon is the ordinary single-map case.
- **D5. Encounters are definitions.** `<dungeon>/maps/<map>/encounters/<name>.json`: a
  named group of creatures (plus map items and conditions) on that map. Each creature
  carries `on_deck`. Adding an encounter to a run copies its creatures in: on-deck ones
  wait in On Deck, the rest are placed. Each run creature remembers its encounter, and
  On Deck groups/deploys by encounter.
- **D6. Runs are play state.** `<dungeon>/runs/<run>/run.json` holds the live state of
  every map: creatures (PCs included), fog, door open/broken/locked, effects, the current
  map. A new run starts fogged, doors at their `map.json` defaults, with the
  encounters a starting set names. Doors are matched map↔run by their edges/cells key.
  A different run is another folder under `runs/` ("Save run as…").
- **D7. Generate Dungeon** writes encounters (one per room, `generated-<seed>-<room>`)
  onto the current map and adds them to the run. It never creates or renames files
  outside `encounters/`. The multi-floor generator writes generated maps into the
  dungeon's `maps/` and one dungeon over them.
- **D8. PCs.** `<campaign>/pcs/<slug>.json`. Load PCs shows a checklist (join/split the
  party per session). Writes back only on an explicit Save PCs, so a bad fight can be
  abandoned.
- **D9. Session per campaign.** `<campaign>/session.json`. Switching dungeons/runs keeps
  the roster, so players are not logged out. The join code persists; the host address is
  never stored (read at startup).
- **D10. Autosave per run.** `<run>/autosave/slot_<k>/` holds the whole run; restoring
  never re-points anything (as M6.4).
- **D11. Migration, not dual reading.** A one-time tool converts the old layout; the
  loader reads only the new one. Old files move to `<campaign>/_archive/`, never deleted.
- **D12. One path module.** All path construction and the D3 lookup live in a new
  `gui/save_layout.py`. Nothing else concatenates sidecar suffixes. Tests use a fixture
  campaign built in a temp dir by `test_helpers.py`.

## Migration (step 9)

Dry run by default (prints every move and merge), `--apply` to execute. Old files go to
`<campaign>/_archive/` as-is.

**Sithicus** — PCs Sabalath, Java of the Indies. Library map `nedragaard-keep` (the jpg
and the newest `map.json`: all seven terrains share the same 25 doors and edge overrides).
Dungeon `nedragaard-keep`, one map.
| old base | → | note |
|---|---|---|
| `…-player`, `…_pcagents` | PCs → `pcs/` | byte-identical; archived |
| `…_pc` | PCs → `pcs/` | duplicate Sabalath dropped |
| `…_dungeon`, `_dungeon_dungeon`, `_dungeon_dungeon_dungeon` | encounters `generated-1/2/3` | |
| `…_pc_dungeon` | run `main` | 44 agents kept as-is for the DM to prune; confirm in the dry run that this is the live one |

**Descent Into Avernus** — PCs Fergus, Tiza. Every image (18) into the library;
Elfsong's `map.json` with it. Dungeon `boneyard`: its creatures → run `main`, its
non-PC creatures also → encounter `boneyard`; autosave moves with the run.

**Curse of Strahd** (renamed from Castle Ravenloft) — PCs Aodhan, Hilaria, Keef Girgo,
Seungho, The Menacing Shadow.
- Library: the original page images (`main_floor_ravenloft.png`, …).
- Dungeon `castle-ravenloft`: the manifest's 10 maps, staircases, room labels. Each map's
  `_frame.png` and terrain go in as the dungeon override (D3). Each page's current
  creatures → run `main` (the campaign is mid-run); its non-PC creatures also → one
  encounter per map (`migrated`), for the DM to split later. Orphan pages
  (`high_tower_peak_map10`, `north_tower_peak_map9`) are archived.
- Dungeon `church-of-st-andral`: `ChurchOfStAndral.png` (moved in from `encounters/`) and
  its terrain/lighting; Feast phase 2 → encounter `feast-phase-2` + run `main`. Phase 1
  is archived (not saved correctly; to be redesigned).
- Archived untouched: `before_*`, `ladders_v*`, `staircases_v*`, `pre_*`, `standalone`,
  `*.bak`/`.before_*`, `*_32px.png`, raw `00x.jpg`, `simplemap_strahd_*`,
  `randencounters.py`, the random-encounters `.md`.

## Steps

1. `gui/save_layout.py` (D12, D3 lookup) + fixture campaign + unit tests. No behaviour
   change. **Done:** `Campaign` / `DungeonLayout` (paths, listings, `resolve` /
   `write_path` / `image` / `calibration_warning`), `slugify` / `unique_slug`,
   `find_campaign`; `make_fixture_campaign` in `tests/test_helpers.py` (its
   `dungeon.json` is a placeholder until step 2); `tests/test_save_layout.py` (7).
2. Dungeon model: `dungeon.json`; a single map opens as a one-map dungeon.
   `gui/dungeon.py` loads/saves it (D4).
3. Map files: `map.json` / `lighting.json` through the D3 lookup, copy-on-write (D2, D3).
4. Runs: `run.json` save/load across all maps, page switching, Save run as (D6).
5. Encounters: definitions, add-to-run, On Deck by encounter, Generate Dungeon,
   multi-floor generator (D5, D7).
6. PCs folder: Save PCs, Load PCs checklist (D8).
7. Campaign session + roster lifetime (D9).
8. Autosave ring under the run (D10).
9. File browser / DM menus / `run.sh` / tools (`encounter_generator.py`,
   `dungeon_from_png.py`, `rescale_to_grid.py`, `ladders_to_staircases.py`), import
   into library (D2).
10. `tools/migrate_layout.py`; dry run reviewed with the user, then applied to the three
    campaigns (D11).
11. Docs (`memory/`, `CLAUDE.md` file names), suite green.
