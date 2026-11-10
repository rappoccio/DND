# Enspelled Items Plan

Weapons, armor and items that cast spells without spending spell slots. First examples:
**Mace of Terror** (`weapons.json`, Fear 2/day, DC 15), **Doss Lute** and **Icon of Ravenloft**
(`items.json`). Spell scrolls come later and reuse the same mechanism (see *Future*).

## Step 0 — decisions (frozen 2026-11-10)

Changes to this set need a dated amendment with a reason, agreed by the user.

| # | Decision |
|---|----------|
| D0 | **Charges live on the item, not on the spell.** An item's remaining uses survive handing it to an ally, a chest, the floor and save/load. Dropping and picking up an item never refills it. |
| D1 | **Save DC / spell attack.** An item may author `spell_dc` / `spell_attack`; when it doesn't, the holder's own values are used. Items meant for non-casters (the mace) should author `spell_dc`. |
| D2 | **Item casts are exempt from the one-slot-per-turn rule** (`canCastLeveledSpell`). The 2024 rule is about expending slots; item casts expend none. |
| D3 | **`"99"` = at will**, same convention as mobs (`AT_WILL_USES` in `read_stats_from_csv.py`). For items the engine never decrements a 99 group, and the UI shows "at will", not "99/day". |
| D3a | **`spell_overrides`** — `{spell name: {spells.json field: value}}`, applied over the catalog record before the spell is granted. Generic: any field. First use: the Icon's Protection from Evil and Good with `requires_concentration: false`. |
| D4 | **Two cost models, both in v1**, and an item may have both: per-spell N/day (`item_spell_groups`, key = uses/day) and a shared charge pool (`charges` + `charge_spells`, key = cost per cast). A pool spell is castable only when the pool has ≥ its cost. |
| D5 | **Attunement.** `requires_attunement: true` items grant nothing until the DM ticks *Attuned* for that creature. Items without the flag grant their spells just by being carried. More than 3 attuned items shows a **warning**, not a block. The attune switch is the hook for curses later. |
| D6 | **Item spells cast at the spell's base level.** "Cast at Nth level" items are a known limitation (`memory/known_limitations.md` § Enspelled items). |
| D7 | **No `spell_indices` on items.** The spell list is derived from the union of `item_spell_groups` and `charge_spells`; a second list could only drift. |
| D8 | **New `ItemType` `Wondrous`**: an item with no Use Item effect of its own (lute, icon). Its spells carry their own casting time; its `action_type` is `NoAction`. |
| D9 | **"Carried" means:** an `items` row for items, any `weapons` row for weapons, a worn `armor` slot for armor. |

### JSON schema (items.json / weapons.json / armor.json)

```json
"requires_attunement": true,
"spell_dc": 15,                     // optional (D1)
"spell_attack": 7,                  // optional (D1)
"item_spell_groups": {"1": ["Fly", "Levitate"], "99": ["Light"]},
"charges": {"max": 7, "regain": "long_rest"},
"charge_spells": {"1": ["Burning Hands"], "3": ["Fireball"], "4": ["Wall of Fire"]},
"spell_overrides": {"Protection from Evil and Good": {"requires_concentration": false}}
```

Runtime state, saved with the item (not authored): `attuned`, per-spell uses remaining for the
groups, and current charges for the pool.

### Split of responsibilities

- **Python** resolves catalog records: it reads the item's spell names, looks them up in
  `spells.json`, applies `spell_overrides`, and hands the engine ready-made `Spell` objects tagged
  with their source item (the same place NPC spells are resolved today).
- **C++** owns cost and state: castability, decrementing uses/charges, DC/attack override at
  resolve time, the long-rest refill. A tagged spell takes a new cost branch in the cast path
  (`combat_spells.cpp` "Decrement resources") and in the castable-spells list, ahead of the
  `resource_name` / NPC / slot branches, so it behaves the same for PCs and NPCs.

## Steps

| # | Step | Status |
|---|------|--------|
| E1 | **Data model + loaders.** New fields on `Item`, `Weapon`, `Armor` (D0–D5 schema + runtime state); `ItemType::Wondrous`; bindings; `_dict_to_item` / `_item_to_dict` and the weapon/armor equivalents round-trip every field. Tests: the three example items parse; save → load keeps uses, charges and `attuned`. | committed bc7e702 — `item_spells.hpp` `ItemSpells` carried by value on all three; snapshot mappings; enspelled armor saves as a full dict; `test_enspelled_items.py` |
| E2 | **Engine cost path.** `Spell` gains a source-item tag (kind + carried index/slot + item name) and, for pool spells, a charge cost. Castable list and cast path check/spend the item's state; 99 never decrements; D2 exemption; `spell_dc`/`spell_attack` used when set. `applyLongRest` refills groups to max and pools to `charges.max`. Tests: PC with no slots casts Fear from the mace; uses run out; pool costs gate correctly; at-will never runs out; DC 15 used; long rest refills; a Bard who also knows Fear keeps both entries independent. | committed 1ccf774 — `Spell.item_source/item_slot/item_name/item_charge_cost`; `ItemSpells::canCast/spend`; `rules::itemSpellsFor/itemSpellCastable/spellSaveDcFor/spellAttackModFor`; item branch first in `availableCastableSpells` and the executeSpell cost block, refused up front when the item can't pay, slot_level pinned to base; item DC also on condition repeat saves and persistent-area saves; NPC save/hit estimators use it; `test_enspelled_cost.py`; suite 236/0 |
| E3 | **Grant / revoke lifecycle.** Python helper rebuilds a creature's item-granted spell entries from its carried + attuned items (applying `spell_overrides`). Called on: attune toggle, give/drop/pick up/chest transfer, equip/unequip weapon or armor, encounter/save load, mob spawn. Tests: unattuned item grants nothing; attuning grants; dropping removes; a different creature picking it up gets the *remaining* uses. | done 2026-11-10 — `helpers.item_spell_entries` / `sync_item_spells` (own spells keep their place; stale item entries dropped, new ones appended; idempotent) + `App._sync_item_spells` (spell metadata follows). Hooked: give_item (floor/chest), weapon pickup/drop, Weapons/Armor/Items/Spells dialogs, `_on_weapon_done`, mob spawn, paste, load, and every turn start (catches engine-side throws/disarms/row shifts). Save leaves item entries out of `spell_indices` and the NPC uses maps; `initNpcSpellGroups` skips tagged spells; enspelled items never stack. Attune toggle itself is E4's checkbox → `_sync_item_spells`. `test_enspelled_lifecycle.py`; suite 237/0 |
| E4 | **GUI.** *Attuned* checkbox per inventory row for `requires_attunement` items, with the >3 warning. Spell menu labels: `Fear (Mace of Terror) 2/2`, `… at will`, pool items show `charges 5/7` and per-spell cost. Item info shows the spells. Player-server character sheet shows the same. | done 2026-11-10 — `helpers.item_spell_label / item_spells_summary / attuned_count / attunement_warning`; spell menu takes an item branch first (offered with no slots, cast at base level); Attuned toggle in the Items, Weapons and Armor dialogs, warning counts the other two kinds; Items-dialog rows and the catalog picker show the spells, hover lists them all; side-panel *Item spells* block (PC and NPC); `sheet.item_spells` in `net/view.py` (the player client renders no sheet yet, so it rides unrendered; spell labels reach players through the prompt). Fixed on the way: `ArmorDialog` rebuilt worn armor from name + description, zeroing `ac_bonus`. `test_enspelled_gui.py`; suite 238/0 |
| E5 | **NPC automation.** Automated NPCs/PCs use item spells through the existing chooser (they arrive as ordinary castable spells). Tests: an automated mace-wielder casts Fear; an NPC with no uses left doesn't. | done 2026-11-10 — the chooser already took item spells (E2 made `npcCastSlotLevel` item-aware); gaps closed: Fear added to `control_priority` (no automated creature could pick it before, item or not); `npcIsCaster` skips item spells the item can't pay for now, so a spent mace-wielder resolves Melee/Simple instead of kiting as a Caster; `npcTeleportEscape` pays an item teleport from the item (no slot, no D2 mark). `test_enspelled_npc.py`; suite 239/0 |
| E6 | **Live check** with the three example items, then update `known_limitations.md`. | headless check done 2026-11-10 through the real `App` paths (menu → `_resolve_spell_cast[_aoe]`, `_dm_save` / `_on_load_path_chosen`, `_drop_weapon` / `_pickup_item`, `apply_long_rest`), on a PC with no slots: unattuned grants nothing; attuned lists all 10 rows; Fear rolls vs DC 15 and spends a mace use (2/2 → 1/2), no slot; Icon PfEG stays at will and keeps the caster's Fear concentration (override holds), Lute PfEG spends its 1/1 and takes concentration, the two entries stay independent; Icon Cure Wounds 1/1 → 0/1; uses survive save → load; a dropped mace keeps 1/2 and the new holder can cast it; long rest refills carried items. Side-panel *Item spells* block screenshot-checked. Recorded in `known_limitations.md`: attunement travels with the item; PfEG's catalog record is a no-op Harm/AttackRoll (predates the plan); no player sheet renderer. **Pending: the DM's own `./run.sh` pass.** |

## Future (not in this plan)

- **Spell scrolls**: a consumable carrying `{"1": [spell]}` and a fixed DC/attack (DMG table); the
  row is deleted when its last use is spent. Class-list check ("can you read it") TBD.
- Cast-at-higher-level items (D6).
- Non-full recharges ("regains 1d6+1 charges at dawn"), and "destroyed on the last charge" rolls.
- Curses triggered by attunement.
- **Manual of Bodily Health** (`type: Buff`, a permanent stat increase) — a different mechanic.
  Until it is implemented, an unknown `type` loads as Heal, so it shows as a 0-HP potion.
