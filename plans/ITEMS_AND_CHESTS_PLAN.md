# Items and Chests

**Status 2026-11-09: Step 0 frozen (user: "all good. go for it", P1–P6 accepted). I1–I6
implemented; I7 (live check) is the user's.** Baseline before any code: 223/0.

## Status and handoff (2026-11-09)

- **I1 (C++ model): done.** `item.hpp`: `Item::Key` + `Item::opens`; `MapItem` gains
  `kind` (Weapon / Armor / Consumable), `armor`, `item`, `pid`, `label`, `displayName()`.
  `battle_map.hpp`: `ChestTrap`, `Chest`; `BattleMap::placeMapItem`, `chests()`,
  `chestAt`, `chestIndex`, `addChest` (keeps a free given id; ids from 1, never reused),
  `removeChest`, `clearChests`, `setChest`, `openChest`, `closeChest`, `unlockChest`,
  `breakChest`, `knockChest`, `takeFromChest`, `addToChest`, `setChestTrap`.
  `isBlocked` counts a chest cell for every movement type but Fly. `pickUpItem` refuses a
  non-weapon item (the GUI routes those). Bindings: `MapItemKind` (no `export_values`:
  "Armor" is a class name), `Chest`, `ChestTrap`, `ItemType.Key`.
- **I2 (engine): done.** `combat_contested.cpp`: `attemptPickChestLock`,
  `attemptBreakChest`, `attemptFindChestTrap`, `attemptDisarmChestTrap`,
  `triggerChestTrap` → `ChestCheckResult` / `ChestTrapResult` (`combat_types.hpp`). Door
  functions untouched (A3). Knock aimed at a chest (no door there) unlocks it in
  `combat_spells.cpp` (A2). Tests: `tests/test_chests.py` (14).
- **I3 (persistence): done.** `gui/placed_items.py` (records ⇄ engine objects).
  `run_state.MAP_KEYS` += `items`, `chests`; terrain `items_state` / `chests_state` ⇄ run
  state `items` / `chests` (`PLACED_STATE`). `main._load_terrain` / `_save_terrain` carry
  them; `_save_agents` leaves design items out of `map_items` and writes non-weapon
  dropped items with a `kind`; `_load_agents` / `_clear_agents` keep design items.
- **I4 (Items menu): done.** `gui/items_play.py`; **Items…** shares the Lighting row.
  Place weapon / armor / item (catalog pickers) / key / chest, click-to-place (Esc or
  right-click stops; an item clicked onto a chest goes in it); Chests… / Placed items… /
  Keys… lists; right-click a chest out of combat → editor (name, lock, DCs, Arcane Lock,
  trap, contents, keys, reset, delete). A DM drag moves a design item's cell; onto a chest,
  into it. `items.json` gains "Key".
- **I5 (play): done.** Chest glyph `terrain_dialogs.draw_chest_glyph` (DM sees an amber
  ring on a live unfound trap, a red "!" once found). Chest menu: Open / Close / Look
  inside / Unlock with key / Pick Lock / Break Open / Search / Disarm; contents menu: Take
  each / Take all. Floor pickup handles every kind; armor asks for a slot (A1). Doors get
  "Unlock with key". Use Item skips keys.
- **I6 (player screens): done.** `net/view.py` `terrain.chests` / `terrain.items` under
  the doors' fog rule (DCs, Arcane Lock, hidden traps and shut contents DM-only);
  `net/static/app.js` `drawChests` / `drawFloorItems`. Player *opening* a chest from the
  browser waits on MULTIPLAYER M5f (Interact), as for doors and ladders; the menus are
  `_ask_actor` prompts the creature's controller answers.
  Tests: `tests/test_placed_items.py` (11).
- **Suite: 225/0** (223 + `test_chests.py`, `test_placed_items.py`); `Item::opens` added to
  the board snapshot (`battle_map_serialization.cpp`); map.json gets `items` / `chests`
  only when the map has some, so an untouched map stays untouched.
- **Next: I7**, the user's live check.

## Amendments (2026-11-09, during implementation)

- **A1 (P2):** armor in `armor.json` has no slot, so picking up armor (floor or chest)
  asks which of the six slots to wear it in; a piece worn there is dropped on the cell.
- **A2 (P3/I2):** Knock unlocks a chest (suppresses an Arcane Lock) but does not open it,
  per the spell's text; opening is what sets a trap off, and that needs a creature.
- **A3 (I2):** the door checks were left as they are rather than factored into a shared
  helper — the chest checks are new functions, so door behaviour can't drift.
- **A4 (P1):** keys are bookkeeping, checked in Python (`items_play.key_for`); no engine
  roll is involved. A door's `opens` token is `door:` + its `run_state.door_key`.
- **A5 (schema):** a placed item is `{"pid", "kind", "record", "label", "cell"}` (the
  catalog entry under `record`); see `placed_items.py` for the state shapes.

The ask (user, 2026-11-09): *"I need an "Items" menu to add items to areas. There should
also be a "Chest" icon that can be locked or unlocked like a door."*

## Decided (user, 2026-11-09)

- **D1 — Catalog only.** A placed item is an entry from `weapons.json`, `armor.json` or
  `items.json`. No free-form loot (no "45 gp" notes, no new Pack list).
- **D2 — Design, with play state.** Placed items and chests are authored into the map,
  like doors. Reset / Release restores them; what has been opened, unlocked, broken or
  taken is run state.
- **D3 — A chest blocks its cell**, like furniture. Creatures interact from an adjacent
  cell. It does not block line of sight.
- **D4 — Chests get keys and traps** on top of door-style locks (locked, lock DC, break
  DC, Arcane Lock; Pick Lock, Break Open, Knock).

## What exists today (from the survey that produced this draft)

- `MapItem` (`item.hpp`) is a **weapon on the floor**: `{id, cell, weapon, sprite_path}`.
  `BattleMap::placeItem / pickUpItem / removeItem / getItemsAtCell / getAllItems /
  clearItems`. Created by drops/disarms; saved as `map_items` in the run section
  (`run_state.py`), restored in `main.py` (~15633). DM can drag one (`_begin_item_drag`)
  or right-click → Delete (`dm.show_item_context_menu`); a creature picks up through
  `dm.show_item_pickup_menu` → `_pickup_item`.
- `Item` (`item.hpp`) is a carried consumable from `items.json` (8 entries: potions,
  flasks, Net), in the agent's inventory (`get_agent_items` / `set_agent_items`).
- `Door` (`battle_map.hpp:68`) carries `open, locked, lock_dc, break_dc, broken,
  arcane_lock, arcane_suppressed_turns`. `CombatEngine::attemptPickLock` (Sleight of Hand
  vs lock DC) and `attemptBreakDoor` (Athletics vs break DC, +10 under Arcane Lock) in
  `combat_contested.cpp`. Knock routes through `_pending_spell_opens_doors`.
  `dm.door_options` builds the play menu. Doors split into map.json design + run.json
  state by `run_state.split_terrain`, matched by geometry key.
- Terrain editor tools are `[1]`–`[9]` (Door is `[5]`, Staircase `[9]`).

## Proposed — needs the user's yes before freezing

- **P1 — Keys are catalog items.** `items.json` gains a `Key` type (`Item::Key`): no
  action, never offered in Use Item. A *placed* key carries `opens`: the chests (by id)
  and doors (by geometry key) it unlocks. Carrying it adds **Unlock with <key>** to that
  chest's / door's menu. One catalog entry ("Key") is enough; the placed copy may be
  renamed ("Iron key", "Crypt key").
- **P2 — Picking up armor**: goes into its slot if empty; otherwise the menu offers
  **Swap** (the worn piece is dropped on the cell) or nothing. Consumables merge into the
  inventory by name (quantity adds). Weapons keep today's `_pickup_item` path unchanged.
- **P3 — One trap per chest**: `detect_dc` (best of Wisdom (Perception) / Intelligence
  (Investigation)), `disarm_dc` (Dexterity (Sleight of Hand)), a save (`ability`, `dc`),
  damage (`dice`, `type`, half on success yes/no), optional condition (e.g. Poisoned).
  **Triggers** when the chest is opened or broken while armed, or on a Pick Lock / Disarm
  that fails by 5 or more. Fires once. Hidden from players until found; the DM always
  sees it.
- **P4 — Action costs** match doors: Open / Take an item = the door's Open cost; Pick
  Lock, Break Open, Search for traps, Disarm = an action. Out of combat, all free.
- **P5 — Chests have no HP.** Break Open is the door's check; it never harms contents.
  A broken chest is permanently open.
- **P6 — Out of scope**: mimics, free-form loot (D1), carried-container weight,
  pickpocketing, chests in the RL observation vector (its length is frozen).

## Schema (Step 0.2 fills in and freezes)

map.json (design):
```json
"chests": [{"id": 1, "cell": [12, 7], "name": "Chest 1",
            "locked": true, "lock_dc": 15, "break_dc": 18, "arcane_lock": false,
            "trap": {"detect_dc": 14, "disarm_dc": 15, "save": "Con", "dc": 13,
                     "dice": "2d10", "type": "Poison", "half": true,
                     "condition": "Poisoned"},
            "contents": [<placed item>, ...]}],
"items": [<placed item>, ...]
```
placed item: `{"pid": 7, "kind": "weapon"|"armor"|"item"|"key", "name": "<catalog
name>", "label": "<optional rename>", "quantity": 1, "cell": [c, r], "opens":
["chest:1", "door:<key>"]}` (`cell` only on the floor; `opens` only on keys). The full
catalog record is embedded, as `map_items` already does for weapons, so a later catalog
edit doesn't change a placed item.

run.json (state, per map): `chests: [{"id", "open", "locked", "broken", "trap_found",
"trap_disarmed", "trap_fired", "contents": [...]}]`. Design floor items are copied into
the run's `map_items` (tagged with `pid`) when a run starts or is reset; from then on
`map_items` is the truth, exactly as dropped weapons are today. Adding a design item
while a run is live adds it to the run too.

## Step 0 — before any code (frozen once signed off)

| # | Step | Touches source? | Done |
|---|------|-----------------|------|
| 0.1 | Inventory every reader/writer of `MapItem` / `map_items`, every door-lock path (pick, break, Knock, Arcane Lock, Dispel), item drag/delete, `net/view.py` item and door records, Reset/Release/Load paths. List them here. | No | [x] |
| 0.2 | Freeze the schema above (map.json, run.json, `items.json` Key, placed-item record); define how legacy saves (weapon-only `map_items`) load. | No | [x] (A5; legacy `map_items` load unchanged) |
| 0.3 | Baseline: run `./test.sh`, record the suite count and that the determinism golden / oracle pass, so I2's lock refactor is checked against it. | No (runs only) | [x] 223/0 |
| 0.4 | User answers P1–P6. | No | [x] all accepted |
| 0.5 | User sign-off: the plan is frozen; changes need a dated amendment with a reason. | No | [x] 2026-11-09 |

## Phases (after sign-off)

- **I1 — C++ model.** `MapItem` gains `kind` + `Armor` + `Item` (weapon path unchanged).
  `Chest` struct and `BattleMap::addChest / removeChest / chests / chestAt`;
  `isBlocked` counts chest cells. `Item::Key` + `opens`. Bindings.
  Tests: `tests/test_chests_model.py`.
- **I2 — Engine.** Factor the door's lock checks into one helper shared by doors and
  chests (door behaviour byte-identical: golden + oracle unchanged). `attemptPickChestLock`,
  `attemptBreakChest`, key unlock (chests and doors), Knock / Arcane Lock on a chest,
  trap find / disarm / trigger through the existing save + damage path.
  Tests: `tests/test_chest_locks.py`, `tests/test_chest_traps.py`.
- **I3 — Persistence.** map.json / run.json split for chests and design items
  (`run_state.py`), Reset / Release restore, legacy saves load. Tests.
- **I4 — Items menu (DM console).** New **Items…** button beside Terrain… / Lighting…:
  *Place item…* (catalog picker: Weapons / Armor / Consumables / Keys, then click cells,
  Esc ends), *Place chest* (click a cell → chest dialog: lock, DCs, Arcane Lock, trap,
  contents, which keys open it), *Chests…* (list → edit / go to / delete), *Items on
  this map…*. Right-click a chest in DM mode → Edit chest. Drag/delete of floor items
  reuses today's handlers. Tests through `tests/gui_driver.py`.
- **I5 — Play.** Chest glyph (closed/open lid; gold / purple padlock as doors; DM-only
  trap mark, shown to all once found). Chest menu: Open, Pick Lock, Break Open, Unlock
  with <key>, Search for traps, Disarm, Take <item> / Take all. Pickup for armor,
  consumables and keys (P2). Use Item skips keys. Tests.
- **I6 — Player screens.** `net/view.py`: chests and floor items under the door fog rule;
  lock state shown, trap hidden until found, contents sent only once open. Menus are
  `_ask_actor` prompts owned by the creature's controller, as for doors. Tests.
- **I7 — Live check** by the user.
