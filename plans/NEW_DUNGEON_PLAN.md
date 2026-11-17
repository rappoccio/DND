# New Dungeon → campaign dungeons

**Status 2026-11-16: Step 0 frozen (D1–D7; U5 reversed, version 1 kept). Step 1 done
(`gui/campaign_import.py`, `tests/test_campaign_import.py`, 258/0, committed bc4dd64). Step 2 done
(`campaign_import.new_dungeon` / `Scene` / `pc_conflicts`, 258/0). Step 3 done
(`gui/pc_sheets.py`, `tools/migrate_pc_play_state.py`, 259/0; the three campaigns
migrated 2026-11-16). Step 4 next.** Came out of the request that New Dungeon
create `encounters/<campaign>/<dungeon>/` and bring in the map, terrain and PCs, instead of
writing an old-style `<map>.dungeon.json` next to the map.

Builds on plans/SAVE_LAYOUT_PLAN.md (D1–D12). That plan already has the layout,
`save_layout.Campaign` / `DungeonLayout` and `CampaignStore`. New maps reached the layout
only through the hand-run `tools/migrate_layout.py`. This plan gives the app its own way
to create campaign dungeons. Version 1 dungeons stay (U5, reversed): a random encounter
may want less state than a campaign run.

## Today

- `_dungeon_new` (`gui/main.py`) writes a **version-1** `<map>.dungeon.json` next to the
  current map. The scene keeps its loose `_agents.json` / `_terrain.json` files
  (`LegacyStore`).
- Version 2 (campaign) dungeons open through `_open_campaign_dungeon` → `CampaignStore`.
- The splitting logic lives only in `tools/migrate_layout.py`: `_split`,
  `run_section_from`, `encounter_doc`, `add_pcs`. It sits on top of `run_state.split_terrain`.
- PCs: `<campaign>/pcs/<slug>.json` exists, and Load PCs opens there. Nothing loads PCs
  automatically. Each run's `run.json` keeps its own copy of every creature, PCs included.

## Decisions (user, 2026-11-16)

- **U1. Copy, never move.** New Dungeon copies the art and writes new files. The source
  map and its sidecars stay where they are (`maps/` is shared by tests and other dungeons).
- **U2. Every dungeon in a campaign takes its PCs from the campaign's `pcs/` by default,
  unless something says otherwise.**
- **U3. A PC is a creature with `faction == PC_FACTION`** (the flag the tracker and
  Load PCs already use). `controller` is a multiplayer seat, not "is a PC".
- **U4. New Dungeon while in a campaign makes another dungeon in the same campaign.**
- **U5. Version 1 (loose `.dungeon.json`) dungeons stay**, reversing the first answer:
  random encounters may want less state than a campaign run. Agreed 2026-11-16 along with
  D3 (items picked up go to the sheet), D4 and D2's art reuse rule.

## Step 0: frozen 2026-11-16

- **D1. Dialog.** New Dungeon asks for:
  - **Campaign:** a list of `encounters/*/campaign.json` plus "New campaign…" (typed
    name). Preselected and fixed when a campaign is open.
  - **Dungeon name:** typed, then slugified. A folder name that's already taken gets
    `-2`, `-3` (`unique_slug`).
  - **Start map:** the current map, or one from the campaign's map library (`maps/<map>/`)
    when a campaign is open.

  It's refused during combat, and on a map with no grid (as today).
- **D2. What a loose map writes** (U1):
  - **Art:** `<campaign>/maps/<map>/<image>`, unless the library already has that map
    (same name and same bytes → reuse it; same name, different bytes → `<map>-2`).
  - **Map facts** (walls, regions, edges, grid, lighting) → library `maps/<map>/map.json`.
  - **Dungeon extras** (staircases, door links, staging cells) → the page in
    `<dungeon>/dungeon.json`, as a single-map dungeon at origin (0, 0, 0) with
    cols/rows filled in.
  - **Play state** (fog, door states) and **non-PC creatures** → `runs/main/run.json`.
  - **Non-PC creatures** also → `<dungeon>/maps/<map>/encounters/initial.json`, so the
    dungeon has a design-side encounter. Release V0 comes from `ensure_first_release`.
  - **PCs** → see D3.
  - **Session:** the campaign's `session.json` is created if missing (D9 of the
    save-layout plan).

  It then opens the result with `_open_campaign_dungeon`.
- **D3. PCs are campaign-level (U2).** Proposal:
  - `pcs/<slug>.json` is the PC's **sheet**: stats, class, spells, items.
  - A run stores, per PC, only its **play state**: cell, map, HP, slots and resources
    used, conditions, carried consumables.
  - When a run opens, every PC in the run's **party list** is built from its sheet, and
    then its play state is laid over it.
  - **Party list:** `campaign.json` `"party"` (default: every file in `pcs/`). A dungeon
    or a run may set its own `"party"` to override it ("unless otherwise specified").
  - A PC with no play state on this map yet is placed on the page's staging cells (else
    the entry map's), and stays off-board on deck if there are none.
  - Save PC / level-up writes the sheet, so every dungeon sees it.
  - Items picked up go to the sheet. HP and slots used stay in the run. Max HP comes
    from the sheet, so a level-up shows up everywhere.
- **D4. PC already in `pcs/` when New Dungeon brings one in.** The campaign's sheet wins.
  The DM is asked once: "Update sheets from the map: Rasha, Gilly?" (Update / Keep).
- **D5. New Dungeon inside a campaign (U4)** writes only `<dungeon>/dungeon.json` (one
  map, from the library) and an empty `runs/main`. PCs come from the party (D3).
- **D6. Shared conversion code.** `_split`, `run_section_from`, `encounter_doc` and the
  PC extraction move from `tools/migrate_layout.py` into `gui/save_layout.py` (or a new
  `gui/campaign_import.py`). The tool imports them from there.
- **D7. Version 1 kept (U5).**
  - The New Dungeon dialog's campaign list gets a **"No campaign (loose)"** entry. It
    writes a version-1 `<map>.dungeon.json` next to the map, exactly as today.
  - Opening, Add Page, floors and staircases on version-1 dungeons are unchanged, and so
    are their tests and tools.
  - There is no converter from version 1 to a campaign.

## Steps (after Step 0 is frozen)

1. Move the D6 helpers into `gui/`; the migration tool imports them. No behavior change;
   tests for the split / merge round trip.
2. `campaign_import.new_dungeon(campaign_root, name, scene…)`: the D2 / D5 writers,
   headless and tested on temp dirs. *Done:* PCs stay in the run as well as `pcs/` until
   step 3. A reused library map whose `map.json` / `lighting.json` differs gets the
   dungeon's own copy. A scene with no lighting on a reused map reads the library's.
3. PCs from the party (D3): sheet + play state, party list, staging placement, Save PC
   and items picked up write the sheet. Migrate the three campaigns' runs to
   play-state-only PCs (on copies first, the way the layout migration was done).
   *Done* (`gui/pc_sheets.py`, through `CampaignStore.creatures` / `write_creatures`):
   - A PC is sheet-backed when `pcs/<slug>.json` exists. The run keeps its play keys
     (cell, on deck, HP, temp HP, slots left, buff bookkeeping, one-shot uses) tagged
     `pc_sheet`; every save writes the rest to the sheet when it changed. So Save PC,
     level-ups, pickups and loadout changes all reach the sheet with no special case.
   - **Items are on the sheet**, weapons and armor too: a potion drunk in one dungeon is
     gone in all of them. "Carried consumables" in D3's play-state list was read as
     this, since a pickup has to reach every dungeon.
   - **Unsettled PCs are held whole.** Aid, Haste, Longstrider, Wild Shape and the like
     rewrite base numbers (max HP, AC, speed) while they last, so a PC under one, or
     the target of any active condition, is stored whole (`pc_whole`) and its sheet is
     not written until a save after it settles.
   - An old run's untagged PC record reads as play state over its sheet (sheet wins).
   - Party: run `"party"` > `dungeon.json` `"party"` (new `Dungeon.party`) >
     `campaign.json` `"party"` > every sheet. Missing party PCs join on open
     (`App._party_arrives`): the showing page's staging cells, else the entry page's,
     else on deck. Load PCs and arrivals share `App._merge_pcs_here`.
   - `new_dungeon` stores the scene's PCs as play state; a kept sheet (D4) is not
     overwritten.
   - Migration: `tools/migrate_pc_play_state.py` reports where a run's record differs
     from the sheet, `--prefer-run NAME@dungeon` takes the sheet from that run, and a
     dungeon whose runs hold only part of the party gets a `"party"` pin. Applied with
     Keef Girgo@castle-ravenloft (level 8 there, sheet was 6), Tiza@boneyard (player
     seat), Sabalath and Java of the Indies@nedragaard-keep (run newer than sheets);
     castle-ravenloft pinned to its four PCs (no Seungho). Backups beside each file as
     `*.pre-pc-sheets`.
4. The New Dungeon dialog (D1, D4) and opening the result.
5. Live check with `run.sh`: TestDNDMap → new campaign; a second dungeon in Sithicus;
   PCs follow between dungeons.
