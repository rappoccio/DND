# Multiattack Recipes — Weapon-List Generalization + Recipe Authoring

**Status:** PHASE 1 COMPLETE — weapon-list generalization built + green 2026-07-02 (engine/GUI/serializer/tests; migration script written, not yet run). PHASE 2: Bucket A ✅ live; Bucket B ✅ script ready (`tools/author_bucket_b.py`, USER runs); Bucket C ✅ done-by-absence + guarded (`tools/verify_legacy_multiattack.py`). Bucket D (recharge-feature auto-use) ✅ DONE — built clean + green 2026-07-03. Bucket E (non-SRD 2-melee) ✅ SCRIPT READY — `tools/author_bucket_e.py`, 32 recipes, USER runs `--write`.
**Decisions locked:** (1) weapons become a **flat list** `[Attack 1, Attack 2, …]`; (2) **model first, then recipes**; (3) free-combo monsters stay legacy.
**Engine multiattack mechanism:** already DONE (`MULTIATTACK_PLAN.md`). Recipe = ordered `[[slot,count],…]`, empty ⇒ legacy `num_attacks`.
**Authoritative data:** `gui/DND2024_MonsterStats.json` (hand-authored — NEVER re-run the CSV→JSON converter). SRD (`SRD_CC_v5.2.pdf`) = ground-truth for multiattack *text*.

---

## Why the refactor (the constraint the vector removes)
Weapons are stored today as `std::array<Weapon,3>` = **[main_hand, off_hand, ranged]**. That caps a monster at 3 distinct weapons, which breaks the SRD for e.g. **Pit Fiend** (Bite + 2 Devilish Claw + Fiery Mace = 3 distinct melee + a ranged) and **Chimera** (Ram + Bite + Claw = 3 melee). A recipe references slot indices, so with only 3 slots there's nowhere to put the 4th attack. Generalizing to a variable-length list lets a recipe say `[[0,1],[1,2],[3,1]]`.

### What is NOT a blocker (verified)
- **NPC melee/ranged selection is already type-driven**, not slot-driven: `npcSelectWeapon`/`npcSelectRangedWeapon` (`combat_turn.cpp:1169–1197`) loop over the weapons and branch on `w.type == Melee/Ranged`. The only "3" there is the loop bound + the array type. → *This is exactly the "type==ranged, not slot==ranged" the design wants; the code already does it.*
- **Two-weapon fighting is already flag-driven**: TWF reads `Weapon.off_hand` (a bool on the weapon), e.g. `main.py:3462, 3549, 3571, 3698`; the serializer already round-trips `off_hand` (`helpers.py:310, 335, 390`). → *Off-hand identity does not depend on slot index.*

### Remaining slot-index assumptions to convert
- **Equip / pickup logic** assumes slot 2 == ranged, slots 0/1 == melee: `main.py:3249–3258` (`EMPTY(weapons[2])` for ranged, `weapons[0]/[1]` for melee). Convert to: place by `weapon.type` into the first empty compatible slot (append if none).
- **Weapons-dict builders** hardcode the three keys: build helper `main.py:1256–1261`; save `main.py:9381–9382`; load `agent_loader.py:283–299`; template `helpers.py`. Convert to list form.
- **Debug prints** naming slot0/1/2 (`main.py:3091` etc.) — cosmetic.

---

## PHASE 1 — Weapon list generalization (engine + GUI + serializer + data migration)
**One rebuild. Opus edits + writes tests; USER builds + runs tests.**

### 1A. C++ storage & API
- `battle_map.hpp:209` `std::array<Weapon,3> weapons;` → `std::vector<Weapon> weapons;` **(invariant: always ≥3, empty-padded)** so the PC path's `weapons[0/1/2]` stays valid.
- `getAgentWeapons`/`setAgentWeapons` signatures: `std::array<Weapon,3>` → `std::vector<Weapon>` at `battle_map.hpp:339–340`, `combat.hpp:1216–1217`, `combat_state.cpp:88–93`.
- `agent.hpp:457` `wild_shape_saved_weapons` (array<3>) + `activateWildShape` (`combat.hpp:2236`) → `std::vector<Weapon>`.
- All `std::array<Weapon,3>` locals + `for (i=0;i<3;…)` bounds → `weapons.size()` (combat_turn.cpp, combat_attack.cpp, combat_riders.cpp, combat_movement.cpp, combat_resources.cpp, combat_spells.cpp, battle_map.cpp — ~30 sites). Drop the `std::clamp(w,0,2)` slot clamps (e.g. `combat_turn.cpp:1277`) → bounds-check against `size()`.
- `rpg_bindings.cpp`: `get_agent_weapons`/`set_agent_weapons` already surface a Python list; confirm the vector overload binds (pybind `stl.h` already included).
- **Invariant helper:** on load/set, pad the vector to ≥3 with empty weapons; the "Attack N" list may exceed 3.

### 1B. Serialization → flat list (round-trip in BOTH directions — mandatory)
- **Save** `main.py:9381–9382`: replace the `main_hand/off_hand/ranged` dict with `"weapons": [ _weapon_to_dict(w) for w in get_agent_weapons(...) if w.name ]` (drop trailing empties).
- **Load** `agent_loader.py:283–299`: replace the fixed 3-slot dict read with a list read; pad to ≥3 empties; `set_agent_weapons`.
- **Back-compat shim:** loader accepts BOTH the legacy dict `{main_hand,off_hand,ranged}` AND the new list, so old encounter/PC saves still load. Detect by `isinstance(weapons, dict)`.
- `helpers.py` `_weapon_to_dict`/`_dict_to_weapon` unchanged per-weapon (they already carry `off_hand`, `type`, ranges).

### 1C. 609-record JSON migration (`gui/DND2024_MonsterStats.json`)
- One-time additive script: for each record, `weapons: {main_hand,off_hand,ranged}` → `weapons: [<filled weapons in order>]` (drop empty-string slots). Preserve every field. Keep a backup; assert count unchanged and every weapon round-trips.
- The `off_hand` flag on any weapon carries over unchanged.

### 1D. GUI weapon dialog
- The fixed 3 buttons (Main Hand / Off Hand / Ranged; "Drop Main Hand"/"Drop Off Hand" at `main.py:1005–1008`) → an **add/remove list of "Attack N"** rows. Each row: name, type (melee/ranged), damage, reach/range, mastery, `off_hand` checkbox (kept for PC TWF).
- Equip/pickup (`main.py:3249–3258`): place a picked-up weapon into the first empty slot whose emptiness/compat matches by `weapon.type`; append a new slot if none free.

### 1E. Verify (USER runs)
- Regression: `run_all_tests.py` green (esp. TWF, ranged, Wild Shape, pact/psychic-blade synthetic-weapon tests, drop/pickup).
- Live smell test: a PC dual-wielder still bonus-attacks off-hand; an NPC archer still kites; a 3-weapon monster (existing) still fights. THEN Phase 2.

---

## PHASE 2 — Recipe authoring (data only, no rebuild)
Runs on the new list model. Additive `multiattack` key per record; script asserts `sum(counts) == num_attacks` and every referenced index is a non-empty weapon. Spot-check live like the vampires.

### Verified reference pattern — VAMPIRES (already live)
`Vampire` slots {0: Grave Strike, 1: Bite} → `[[0,2],[1,1]]`; `Vampire Spawn` {0: Claw, 1: Bite} → `[[0,2],[1,1]]`.

### Bucket A — clean fixed-split (17). ✅ DONE 2026-07-02 (`tools/author_bucket_a.py`; 25 records now carry a recipe = 8 vampires + 17 here). Recipes reference slots 0/1 only, so valid under the current dict-form weapon layout — no rebuild, no migration needed. Slot order + `sum(counts)==num_attacks` verified for all 17.
| Monster | slots 0/1 | recipe |
|---|---|---|
| Brown Bear | Bite/Claw | `[[0,1],[1,1]]` |
| Bone Devil | Claw/Sting | `[[0,2],[1,1]]` |
| Otyugh | Bite(r5)/Tentacle(r10) | `[[0,1],[1,2]]` |
| Xorn | Bite/Claw | `[[0,1],[1,3]]` |
| Wyvern | Bite/Sting | `[[0,1],[1,1]]` |
| Grick | Beak/Tentacles | `[[0,1],[1,1]]` |
| Ettercap | Bite/Claw | `[[0,1],[1,1]]` |
| Ettin | Battleaxe/Morningstar | `[[0,1],[1,1]]` |
| Giant Crocodile | Bite/Tail | `[[0,1],[1,1]]` |
| Tyrannosaurus Rex | Bite/Tail | `[[0,1],[1,1]]` |
| Unicorn | Hooves/Radiant Horn | `[[0,1],[1,1]]` |
| Purple Worm | Bite/Tail Stinger | `[[0,1],[1,1]]` |
| Bearded Devil | Beard/Infernal Glaive | `[[0,1],[1,1]]` |
| Balor | Flame Whip/Lightning Blade | `[[0,1],[1,1]]` |
| Giant Scorpion | Claw/Sting | `[[0,2],[1,1]]` |
| Cloaker | Attach/Tail | `[[0,1],[1,2]]` |
| Tarrasque | Bite/Claw-or-Tail | `[[0,1],[1,3]]` |

### Bucket B — authored via `tools/author_bucket_b.py` — ✅ SCRIPT READY (USER runs it)
The script is self-contained: for **just Pit Fiend and Chimera** it reshapes `weapons`
dict→flat-list (same convention as the migration), appends the missing 4th melee weapon
at index 3, and writes the recipe. So it does NOT require the full-bestiary migration to
have run first (idempotent if it has). Validated: `sum(counts)==num_attacks`, every
referenced index non-empty, writes a `.bak_bucketB`.
- **Pit Fiend** (na=4): Bite (slot 0) + 2 Devilish Claw (slot 1) + **Fiery Mace added at slot 3** (2d6 Bludgeoning + 6d6 Fire) → `[[0,1],[1,2],[3,1]]` (slot 2 stays the necrotic ranged, unused). Confirmed: main_hand=Bite (piercing+poison per action_notes), off_hand=Devilish Claw (Force).
- **Chimera** (na=3): Bite (slot 0) + Claw (slot 1) + **Ram added at slot 3** (2d6 Bludgeoning, **mastery Topple** — copies the Quarterstaff, for the SRD Ram's Prone) → `[[0,1],[1,1],[3,1]]` (slot 2 empty `{}` placeholder; Fire Breath stays the separate `BreathFireConeLow` recharge spell). Chimera also gets `stats.weapon_mastery: 1` (the engine gates masteries on wielder `weapon_mastery > 0`; Djinni, the other Topple monster, is 1).
- **Barbed Devil / Medusa**: CONFIRMED **LEGACY** (no recipe) — both have a ranged mode (Hurl Flame / Poison Ray) the free-combo `num_attacks` path should be free to choose over melee. Guarded in `tools/verify_legacy_multiattack.py`.

**USER steps (Phase 2, data-only, no rebuild needed):**
1. `python3 tools/author_bucket_b.py --write`
2. Regenerate the golden AFTER step 1 (needs the built vector-weapon engine):
   `python gui/test_multiattack_recipes.py --update` — inspect the Pit Fiend/Chimera diff, then commit.
3. `python3 tools/verify_legacy_multiattack.py` should print OK.

### Bucket C — LEGACY, no recipe (~55 read from SRD) — ✅ DONE (implemented by absence + guarded)
No data to author: a record with no `multiattack` key already falls through to the legacy
`num_attacks` free-combo path, which is what these want. Intent is locked in by
`tools/verify_legacy_multiattack.py`, which asserts the named legacy roster carries **no**
recipe so a later authoring pass can't silently regress one. Name resolutions:
"Veteran"→`Warrior Veteran`, "Centaur"→`Centaur Trooper`/`Centaur Warden`; true Giants
listed explicitly (NOT `Giant <beast>`, since Giant Crocodile/Giant Scorpion are Bucket A);
all Dragons matched by name.

Roster (free-combo "X **or** Y", same-weapon ×N, replace-one "…replace one with Spellcasting/Breath"): all Dragons, all Giants, Assassin, Bandit Captain, Djinni, Efreeti, Lich, Mage/Archmage, Manticore, Merrow, Priest, Scout, Spirit Naga, Wight, all Weres, Ape, Ghoul, Roc, Solar, Treant, Warrior Veteran, Iron Golem, Gladiator, Pirate(+Captain), Salamander, Oni, Mummy Lord, Dryad, Guard Captain, Hobgoblin Captain, Horned Devil, Ice Devil, Centaur, Drider, Earth Elemental, Tough Boss. **Roper** = leave to its bespoke Reel handling (`monster_pull_rider`).

### Bucket D — Special mobs (recharge features) — ✅ DONE (built clean + green 2026-07-03)
Many of the mobs in the SRD have special abilities on recharge. Dragons are the obvious example and the eponymous monster of this game. They have breath weapons (explicitly functional in this engine with `npc_spell_recharge`) on a recharge of X turns (usually 5-6). Any monster with a rechargeable feature should use it as often as it is available.  This should work with the `PreferAOE` automation strategy.

**Implemented (C++, needs one rebuild):**
- **Gate fix (root cause)** — `availableCastableSpells` (`combat_spells.cpp`) treated ALL level-0 spells as
  at-will cantrips, so a breath (which ships as a level-0 catalog spell with `uses_max`/`recharge_min`)
  bypassed the NPC uses/expended check and showed as castable even when expended. Now a level-0 spell that
  is a limited-use/recharge NPC action falls through to the NPC uses/expended gate. This also fixes the
  manual cast picker re-offering a spent breath.
- **Auto-use, any strategy** — `runNpcTurn` (`combat_turn.cpp`) now routes ANY automated NPC through the
  AoE executor (`runAoeTurn`) on a turn where it has a currently-available recharge AoE feature
  (`npcHasAvailableRechargeAoe`: `recharge_min>0` + a live use + an AoE blast shape). So a Simple/preferMelee
  dragon still breathes when the breath is up, and bites (its normal weapon turn) when it is on cooldown.
  `PreferAOE` already routed to `runAoeTurn`, so it is excluded from the extra check. `runAoeTurn` still
  respects friendly-fire / ally-sparing and falls back to a weapon turn when the breath can't catch an enemy.
- **Resume safety** — a top-of-`runNpcTurn` guard re-enters `runAoeTurn` when a parked turn is mid-flight
  (`aoe_cast_launched`/`aoe_moving`), because the recharge feature that triggered the route is expended once
  the cast launches and the fresh-turn heuristic would otherwise mis-route the resume.
- **Tests** — `test_npc_automation.py`: `test_recharge_breath_gating_respects_expended` (gate fix),
  `test_recharge_breath_used_regardless_of_strategy` (Simple dragon breathes), and
  `test_recharge_breath_on_cooldown_falls_back_to_weapon` (expended → bite).

Scope: covers **damaging AoE breath weapons** (the derived `Breath<…>` catalog spells) — the recharge
features that exist in the bestiary today. Single-target / condition-only / attack-slot recharges remain
deferred (see NPC_USES_RECHARGE_PLAN.md). Files: `combat_spells.cpp`, `combat_turn.cpp`, `combat.hpp`,
`test_npc_automation.py`. Built clean + all `test_npc_automation.py` green 2026-07-03.
### Bucket E — non-SRD monsters — ✅ SCRIPT READY (`tools/author_bucket_e.py`, USER runs it)
**Scope collapsed on inspection.** Of the 365 multi-attack records with no recipe, almost all need
nothing: 164 are single-melee (`[[0,na]]` == the legacy path already), 150 are melee+ranged (free
melee-or-ranged choice the legacy path already makes right), and 0 are weaponless-with-spells (none
exist — every caster carries a token melee weapon, driven by its automation strategy, not a recipe).
The only records that genuinely need a recipe are the **2-distinct-melee** ones, where the free-combo
path can't know the split.

`tools/author_bucket_e.py` auto-derives `[[0,1],[1,na-1]]` (lead weapon once, rest with the second —
the standard SRD "one bite/beak + rest claws" shape) for every non-legacy 2-melee monster. It:
- **Imports `LEGACY_NAMES` from `verify_legacy_multiattack.py`** as the single source of the Bucket C
  roster, so the two scripts can't diverge (Lich/Ghoul/Merrow/Roc/Ice Devil/Guard Captain/Barbed
  Devil/Medusa/Roper/the 5 SRD weres are excluded — they'd otherwise be picked up and fail the guard).
- Uses the `action_notes` `Atk N` shorthand only to CORROBORATE the split + set a confidence tag; never
  silently flips it. `CONFIRMED` pins SRD-verified splits; `OVERRIDES` pins any that differ from the
  heuristic; `SKIP` drops records left legacy.
- Validates `sum(counts)==num_attacks` + both slots are non-empty melee; writes `.bak_bucketE`; dry-run
  by default, `--write` to author.

**Result: 32 recipes, 30 high / 2 med confidence.** SRD-verified (user-confirmed): Arcanaloth,
Cockatrice Regent (1 Bite + 2 Talons), Gnoll Fang of Yeenoghu (1 Bite + 2 Bone Flail), Goristro
(1 Gore + 2 Slam). Left legacy per user: Phaerimm Elder, Queen Forfallen (`SKIP`). Remaining 2 med
(Beast of Malar, Werewyvern) ship on the layout-inferred `[[0,1],[1,2]]`. All 32 reference slots 0/1
only (dict-form), so valid under the current weapon layout — no migration needed (same as Bucket A).

Open (non-blocking): Jackalwere/Wereraven/Werewyvern get recipes because the guard's were-list is
SRD-only; move them to `LEGACY_NAMES` if "all weres = legacy" is desired.

**USER steps (data-only, no rebuild):**
1. `python3 tools/author_bucket_e.py --write`
2. `python gui/test_multiattack_recipes.py --update` — inspect diff, commit
3. `python3 tools/verify_legacy_multiattack.py` should still print OK



---

## Execution / handoff rules
- Planning now; **code in the loop.** Opus edits + writes tests, then STOPS; **USER builds and runs tests** (memories: user_runs_builds, user_runs_tests, user_owns_git_commits). Never re-run the CSV→JSON converter.
- Phase 1 = one rebuild + GUI; Phase 2 = data only, no rebuild.
- New round-trip fields go in BOTH save (`main.py`) and load (`agent_loader.py`) — the list migration covers both.
