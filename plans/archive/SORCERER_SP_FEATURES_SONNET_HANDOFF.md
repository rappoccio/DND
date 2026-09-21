# Sorcerer SP-Spend Features — SONNET Handoff (2026-06-24)

Two low-risk, high-reuse Sorcerer features that lean entirely on existing plumbing. Both are
**[SONNET]**. Nothing here touches the reaction system or the surge restructure (those are the
remaining [OPUS] items: Wild Magic Controlled Chaos/Tamed Surge, Aberrant Revelation/Warping,
Restore Balance disadvantage-direction — DO NOT start those).

## Ground rules (read first)
- **Do NOT run builds, tests, git, or any state-mutating Bash.** The user runs all builds. Propose
  edits only. (gui/CLAUDE.md)
- **Fix root cause in C++.** No Python-side workarounds. (memory: fix-root-cause)
- **Every new `rpg.Stats` field round-trips in THREE places or it resets on save/reload:**
  1. C++ field on `Stats` (`gui/agent.hpp`) + `def_readwrite` in `gui/rpg_bindings.cpp`.
  2. Load: `dict_to_stats` in `gui/agent_loader.py`.
  3. Save: the save dict block in `gui/main.py` (~line 8336, where `elemental_adept_types` and
     `draconic_affinity_type` are written).
  (memory: stats-serializer-roundtrip) — **TASK A needs this; TASK B needs NO new field.**
- Each task names the **precedent to clone** — match that idiom, don't invent a new shape.
- When done, register new tests in `gui/test_sorcerer.py`'s `__main__` block and leave the user a
  short "what to verify" summary. **You do not build or run — the user does.**

---

## TASK A — Draconic L6 Elemental Affinity: resistance half + element picker  [SONNET]

The **damage half** of Elemental Affinity is already done (`+CHA` to the first matching-type spell
damage roll per turn; see `combat_spells.cpp:683-686, 775, 971`). Two pieces remain:

### A1. Element picker in the Stats dialog (the field has no GUI to set it)
`draconic_affinity_type` (int, a `MagicDamage_t` index, -1 = none) already exists on `Stats`, is
bound, and round-trips (`main.py:8336`-area save + `dict_to_stats`). But **nothing lets the user
choose it** — so the damage half + resistance half are dead without a manual hex edit.

**Precedent — clone the Elemental Adept picker exactly:**
- `ElementPickerDialog` lives at `dialogs.py:872`; already instantiated as `self._element_dialog`
  in `main.py` (`main.py:406`) and in `dialogs.py:1447`.
- The Elemental Adept flow runs through `_on_stats_ok` (`main.py:1728`, see the
  `elemental_adept_types` param + `main.py:1826` assignment gated on `has_feat("Elemental Adept")`).

**What to add:** when the chosen class/subclass is Draconic Sorcerer at L6+, prompt the
`ElementPickerDialog` for **one** of the 5 draconic types only (Acid/Cold/Fire/Lightning/Poison —
NOT Thunder), and write the chosen `MagicDamage_t` index to `stats.draconic_affinity_type`. Gate so
non-Draconic / sub-L6 sorcerers get `draconic_affinity_type = -1`. Mirror how
`elemental_adept_types` is threaded through `_on_stats_ok`'s signature and StatsDialog. The picker
already returns element selections; restrict its offered list to the 5 draconic types (pass a
filtered option set, or filter the result — match whatever shape `ElementPickerDialog` accepts).

**Round-trip:** no new field — `draconic_affinity_type` already round-trips. Just verify the picker
value survives save/reload (it already has a save line at `main.py:8336`-area + `dict_to_stats`).

### A2. Resistance half (spend 1 SP → resistance to the chosen type)
**Rule (2024):** as a reaction-ish option *(model it as a Bonus Action / button in this sim)*, spend
1 Sorcery Point to gain **resistance** to your chosen draconic damage type for 1 hour.

**New state (round-trip all THREE places):**
- `int draconic_affinity_resist_turns{0}` on `Stats` — `>0` means the resistance is active. 1 hour ≫
  any combat, so set it to a large value (e.g. 600 rounds) on activation; tick −1 in `beginTurn`
  (`combat_turn.cpp`, right next to where `draconic_affinity_used_this_turn` is reset). When it hits
  0, restore the multiplier to 1.0.

**Engine method** `activateDraconicResistance(BattleMap& bm, int idx)` in `combat_resources.cpp`
(clone the shape of `activateDragonWings` / `activateTidesOfChaos`):
- Gate `character_class==Sorcerer && sorcerer_subclass==DraconicPath && char_level>=6 &&
  draconic_affinity_type>=0`.
- Require a `Resource* sp = stats.getResource("Sorcery Points")` with `current >= 1`; `sp->spend(1)`.
- `stats.magic_damage_multipliers[(size_t)draconic_affinity_type] = 0.5f;` and set
  `draconic_affinity_resist_turns = 600;` then `setAgentStats`.
- **Precedent for the multiplier write:** `combat_resources.cpp:750` (Aberrant Psychic 0.5×) and the
  reset block at `:873` (back to 1.0×). The `beginTurn` decrement, on reaching 0, sets that index
  back to `1.0f`.
- Declare in `combat.hpp` near the other sorcerer methods; bind `activate_draconic_resistance` in
  `rpg_bindings.cpp`.

**GUI (`main.py`):** add `btn_cbt_draconic_resistance`, shown for Draconic L6+ with `≥1` SP and
`draconic_affinity_type >= 0` and resistance not already active. Mirror the `btn_cbt_tides_of_chaos`
wiring (button creation, draw-gate, click handler → `activate_draconic_resistance`; on success set
`bonus_used = True`). Label e.g. `"Draconic Resist (1 SP)"`.

**Tests (`test_sorcerer.py`):**
- `test_draconic_resistance_spends_sp_and_gates` — L6 Draconic with a chosen type + SP → SP drops by
  1 and `magic_damage_multipliers[type] == 0.5`; L5 / wrong-subclass / no-type-chosen → no-op, no SP
  spent.
- `test_draconic_resistance_duration_ticks` — `draconic_affinity_resist_turns` decrements in
  `begin_turn`; on hitting 0 the multiplier returns to 1.0.
- (Optional) damage worked-example: a Fire spell into the resisted sorcerer takes half.

**DEFER nothing here** — both A1 and A2 are in-scope.

---

## TASK B — Aberrant Mind: Psionic Sorcery (cast psionic-list spells with SP)  [SONNET]

**Rule (2024):** when you cast a level-1+ spell **from your Psionic Spells list**, you may pay
**Sorcery Points equal to the spell's (slot) level** instead of expending a spell slot. (No new
engine rule beyond "spend SP, don't burn a slot" — the cast itself is the normal pipeline.)

This needs **NO new Stats field.** It reuses two things that already exist:
- The Aberrant always-prepared list: `main.py:6100` `_SORCERER_SUBCLASS_SPELLS["Aberrant"]`, granted
  at `main.py:6077-6080`.
- The free-cast path: `SpellAction.free_cast` (set via `self.pending_spell_free_cast`, see
  `main.py:5832` for the Mantle-of-Majesty precedent) makes C++ skip slot consumption.
- The SP resource is `Resource "Sorcery Points"` (see `createSpellSlot` at `combat_spells.cpp:2301`
  for how it's fetched/spent: `stats.getResource("Sorcery Points")` → `sp->spend(cost)`).

### B1. Engine helper (thin, in C++ — keep the rule in the engine)
Add `bool spendSorceryPointsForSpell(BattleMap& bm, int idx, int spell_level)` in
`combat_spells.cpp` (declare in `combat.hpp`, bind `spend_sorcery_points_for_spell`):
- Gate `character_class==Sorcerer && sorcerer_subclass==AberrantPath && char_level>=3 &&
  spell_level>=1`.
- `Resource* sp = stats.getResource("Sorcery Points")`; require `current >= spell_level`;
  `sp->spend(spell_level)`; `setAgentStats`; return true. Else false.
- **Precedent:** the SP fetch/spend/log in `createSpellSlot` (`combat_spells.cpp:2314-2317`).
- Log `"{} spends {} Sorcery Points to cast a level-{} psionic spell"`.

### B2. GUI offer in the cast menu
In `_start_cast_spell` (`main.py:6192`), the leveled-spell loop builds per-slot-level options at
`main.py:6362-6366`. For a caster who is **AberrantPath L3+**, and a spell whose name is in
`_SORCERER_SUBCLASS_SPELLS["Aberrant"]` (the always-prepared psionic list), **add one extra menu
option per castable level**: `"{sp.name} @ {ordinal} (SP)"` that, when chosen:
  1. calls `self.combat.spend_sorcery_points_for_spell(self.bm, caster_idx, slot_lvl)`; if it
     returns False (not enough SP), log and abort that option;
  2. on success, set `self.pending_spell_free_cast = True` then call `_activate(slot, si, slot_lvl)`
     (so the cast resolves at `slot_lvl` for scaling but burns **no slot** in C++).
- Only offer SP-cast for levels the sorcerer could actually pay for (`SP.current >= slot_lvl`); you
  can still offer it even when they have a slot of that level (player's choice).
- Reset `pending_spell_free_cast = False` on the normal slot-cast path so it doesn't leak (it's
  already reset at `main.py:6222` in `_activate`; set it to True *after* `_activate` reads it, or
  thread a flag into `_activate` — simplest is a small `psionic_sp=True` kwarg on `_activate` that
  sets `self.pending_spell_free_cast = True` just before building the SpellAction. Check where
  `_activate` reads/sets `pending_spell_free_cast` and place the True there to avoid the reset
  clobbering it.)

**Helper for the membership test:** build the set once, e.g.
`psionic_names = {s["name"] if isinstance(s, dict) else s for lvls in
_SORCERER_SUBCLASS_SPELLS["Aberrant"].values() for s in lvls}` — confirm the actual shape of the
`_SORCERER_SUBCLASS_SPELLS["Aberrant"]` table first (read `main.py:6100`) and match it.

**Tests (`test_sorcerer.py`):**
- `test_psionic_sorcery_spends_sp_not_slot` — L3 Aberrant casts a known psionic-list spell paying
  SP: SP drops by the spell level, the spell slot of that level is **unchanged**.
- `test_psionic_sorcery_gating` — wrong subclass / L2 / spell NOT on the psionic list → helper
  returns False, no SP spent.
- `test_psionic_sorcery_insufficient_sp` — SP below the spell level → False, no spend, no slot used.

**DEFER nothing here** — Psionic Sorcery is fully in scope. (The Telepathic-Speech utility half of
Aberrant is out-of-combat flavor and already in known_limitations.)

---

## Done-criteria
- Task A: new `draconic_affinity_resist_turns` field bound + round-trips in `agent_loader.py` AND the
  `main.py` save block; element picker writes `draconic_affinity_type`; `activate_draconic_resistance`
  bound; GUI button wired; tests registered.
- Task B: `spend_sorcery_points_for_spell` bound; cast menu offers the SP option for psionic-list
  spells; `pending_spell_free_cast` correctly set so no slot is burned; tests registered.
- Leave the user a "what to verify" note. **Build + tests are the USER's to run.**
