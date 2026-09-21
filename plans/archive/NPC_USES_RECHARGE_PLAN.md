# NPC N/day Attacks + Recharge — Implementation Plan

Two features for monsters/NPCs:

1. **N/day weapon attacks** — a real attack-roll weapon capped at N uses per day
   (refilled on a long rest). Save-based limited "attacks" stay on the existing
   spell N/day path (`Spell::uses_max`/`uses_remaining`).
2. **Recharge (dice only)** — the Monster-Manual "(Recharge 5–6)" / "(Recharge 6)"
   mechanic: once spent, the action is unusable until, at the start of the owner's
   turn, a d6 roll ≥ `recharge_min` restores it. Applies to **both** weapons
   (breath-weapon-as-attack) and spells (save-based breath weapons).

Decisions already made: **recharge is dice-only** (no deterministic cooldown);
**N/day attacks are weapon-level** (new fields on `Weapon`).

## Conventions / gotchas (from memory)
- USER runs all builds, tests, commits. Opus only edits, then hands off.
- New `Weapon` flags MUST go in BOTH `helpers._weapon_to_dict` AND
  `helpers._dict_to_weapon`, and in `main.py`'s save block, or they reset on
  save/reload.
- New `Stats`/`Spell` JSON fields go in BOTH the C++ reader (`map_configs.cpp`)
  and any Python save block.
- C++ is camelCase; Python bindings snake_case (see `rpg_bindings.cpp`).
- Fix engine rules in C++, not Python workarounds.

## New fields
- `Weapon` (`weapon.hpp`): `int uses_max{0}`, `int uses_remaining{0}`,
  `int recharge_min{0}`, `bool expended{false}`.
- `Spell` (`spell.hpp`): already has `uses_max`/`uses_remaining`; ADD
  `int recharge_min{0}`, `bool expended{false}`.

Semantics: `uses_max==0` ⇒ unlimited. `recharge_min==0` ⇒ no recharge. A
pure-recharge action uses `uses_max=1` + `recharge_min=5` (or 6).

---

## Step 1 — C++ engine  ☑ DONE (built green)
After this step: build, smoke-import, then clear cache.

- [x] `weapon.hpp`: add `uses_max`, `uses_remaining`, `recharge_min`, `expended`.
- [x] `spell.hpp`: add `recharge_min`, `expended` (uses_* already present).
- [x] `combat_turn.cpp` `beginTurn`: after the regeneration block, scan the
      agent's weapons + spells; for each `expended` with `recharge_min>0`, roll
      `roll(6)` — if `≥ recharge_min`, clear `expended` and refill
      `uses_remaining = max(uses_remaining, uses_max)`. Logs "<name> recharges
      <action> (rolled d ≥ min)". Persists via `setAgentWeapons`/`setAgentSpells`.
- [x] Weapon attack path: gate in `determineAdvantage` (block on `expended`, or
      `uses_max>0 && uses_remaining<=0`); spend in `applyAttackResult` (the
      committed-attack chokepoint both auto + interactive paths reach):
      `uses_remaining = max(0, uses_remaining-1)` and `expended=true` when
      `recharge_min>0`. Consumed on hit OR miss (a breath weapon expends even if
      targets save).
- [x] Spell path: gate at the offer site (`availableSpells`) on `!expended`; on
      cast set `expended=true` when `recharge_min>0` (NPC branch beside the
      existing N/day decrement).
- [x] `map_configs.cpp`: `spellFromJson` now reads `recharge_min`/`expended`.
- [N/A] `battle_map.cpp` NPC load: no C++ monster-weapon JSON loader exists —
      NPC weapons are built Python-side (`helpers._dict_to_weapon` → `rpg.Weapon`
      → `setAgentWeapons`). The weapon usage fields round-trip there (Step 2/3),
      so nothing is needed in `battle_map.cpp`. (Spells still use
      `initNpcSpellGroups`, untouched.)
- [x] `rpg_bindings.cpp`: expose new Weapon + Spell fields (snake_case:
      `uses_max`, `uses_remaining`, `recharge_min`, `expended`).

Acceptance: builds clean (`-Wall -Wextra -Wpedantic -Wshadow -Wconversion`);
`import rpg_battle_map` works; new fields readable/writable from Python.

---

## Step 2 — Python / GUI  ☑ DONE
After this step: clear cache.

- [x] `helpers.py` `_weapon_to_dict`: serialize `uses_max`, `uses_remaining`,
      `recharge_min`, `expended`.
- [x] `helpers.py` `_dict_to_weapon`: read the same four fields back
      (`uses_remaining` defaults to `uses_max` so a fresh weapon starts full).
- [N/A] `main.py` save block: the encounter-save path already persists weapons
      via `_weapon_to_dict` (main_hand/off_hand/ranged near line 9031), which now
      carries the new fields. No separate manual weapon-dict construction exists.
- [x] `main.py` attack picker (`_start_attack`): new `_weapon_usable` /
      `_weapon_menu_label` helpers — picker labels weapons with `N/M` + `⟳`
      recharge marker; depleted/expended weapons are blocked (auto-select warns,
      multi-weapon menu shows them but selecting is a no-op warning). Legendary
      action menu (`_choose_legendary_action`) blocks an expended/depleted weapon
      without consuming the action.
- [x] `main.py` right panel NPC display (~11356): lists weapon uses (`N/M`) and
      recharge state alongside spells; spell list now includes recharge-only
      (`recharge_min>0`) entries too.
- [x] `main.py` long-rest reset (`_on_long_rest`): refills weapon
      `uses_remaining = uses_max` and clears `expended` on both weapons and
      spells (now persists via `set_agent_spells`/`set_agent_weapons`).

Acceptance: an NPC weapon shows `N/M`, decrements on attack, disables at 0;
expended recharge action shows `⟳` and is disabled; long rest restores all;
save→reload preserves usage/recharge state.

---

## Step 3 — Data + tooling  ☑ DONE
After this step: clear cache.

Design pivot (decided with the user): the bestiary JSON
(`gui/DND2024_MonsterStats.json`) is **authoritative** (the CSV has errors), and
breath weapons live only in free-text `meta.action_notes`. Save-based breath
weapons are modelled as **generic catalog spells** — a "reskin of Burning Hands"
— named `Breath<Element><Shape><Tier>`, referenced per-monster via `spell_indices`
with the recharge value in a new per-monster `npc_spell_recharge` map. Tiers
(Low/Medium/High/Enormous) bucket the **AoE footprint** (size), and each catalog
spell's damage dice come from the bucket's **median actual damage**, so footprint
and damage both stay faithful while the spell stays reusable.

- [x] `tools/derive_breath_weapons.py` (NEW): parses `action_notes`, buckets each
      damaging breath by (element, geometry, size-tier), mints catalog spells
      (median size + median d6 damage), and writes `spell_indices` +
      `npc_spell_recharge` per monster. `cast X` recharges reference an existing
      catalog spell; attack-slot recharges are left to the weapon path. Default
      dry-run; `--write` applies. 0 unparsed.
- [x] `tools/monster_breath_overrides.json` (NEW): the override mechanism for
      size/damage/element outliers (Tarrasque 150ft cone, Colossus 300ft line,
      Sphinx 300ft emanation, Death Knight Hellfire fire+necrotic, Behir line
      width/length fix, Dire Worg bare-size) and deferred specials (Whelm, Death
      Glare, attack-slot recharges, condition-only-via-skip).
- [x] `gui/spells.json`: 38 `Breath<…>` catalog spells appended (Save AoE, d6,
      `uses_max=1`, `recharge_min=0`, `level=0`).
- [x] `gui/DND2024_MonsterStats.json`: 67 monsters now carry a breath
      (`spell_indices` + `npc_spell_recharge`).
- [x] Plumbing the earlier steps missed: spell `recharge_min`/`uses_*`/`expended`
      now round-trip in `helpers._dict_to_spell`/`_spell_to_dict` and
      `main._spell_to_dict`; `main._load_npc_spells_from_record` applies the
      per-monster recharge; the encounter save/restore path persists & restores
      recharge + expended state.
- [N/A] `tools/monster_parser.py`: NOT touched — the parser converts the *CSV*,
      but the design works from the authoritative JSON instead. The CSV→JSON
      regeneration path (`read_stats_from_csv`) is unchanged; the breath deriver
      runs as a post-step on the JSON.

Deferred (per "damaging breaths first" scope): 10 condition-only breaths
(Sleep/Petrifying/Blinding/Repulsion/etc.) and on-hit condition riders on
damaging breaths (Mind Blast Stun, Tarrasque Deafened+Frightened) → a later
"condition pass".

Acceptance: `derive_breath_weapons.py` produces breath spells + per-monster
references with usage/recharge fields; exemplar monsters (Adult Red Dragon
Fire Breath recharge 5-6, Ice Mephit recharge 6, Tarrasque colossal) load with
correct caps.

---

## Step 4 — Tests  ☑ DONE (green 2026-06-29)
After this step: clear cache. (USER runs the suite.)

`gui/test_recharge.py` written. Determinism without RNG seeding: `recharge_min=1`
always recharges (any d6 ≥ 1), `recharge_min=99` never does (no d6 ≥ 99).

- [x] N/day weapon: 3 uses → blocked on the 4th; `begin_turn` doesn't refill a
      pure N/day weapon.
- [x] Recharge weapon: spend → `expended`/blocked; `begin_turn` with
      `recharge_min=99` stays expended; `recharge_min=1` restores + refills uses.
- [x] Recharge spell (save-based breath, NPC branch): same expend/restore cycle.
- [x] Long-rest reset (mirrors `main._on_long_rest`) clears `expended` and
      refills `uses_remaining` for weapon AND spell.
- [x] Save→reload round-trip via `helpers._weapon_to_dict`/`_dict_to_weapon` and
      `_spell_to_dict`/`_dict_to_spell` preserves `uses_remaining`/`expended`.

Acceptance: all assertions pass under the user-run suite.
