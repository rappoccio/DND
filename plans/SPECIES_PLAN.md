# SRD Species — Plan

Drafted 2026-11-24. Source: `character_origins.pdf` (SRD 5.2, pp. 83–86). Status: **Step 0
FROZEN 2026-11-24** — D1 signed off and committed (9380611); D2–D14 signed off by the user the
same day. SP0 audit done 2026-11-24 (results below). SP1 done 2026-11-24 (288/0). SP2 done 2026-11-24
(289/0), committed 7cd4c1b. SP3 done 2026-11-25 (290/0). SP4 done 2026-11-25 (292/0). Next: SP5.

## Scope

The nine SRD species: **Dragonborn, Dwarf, Elf (Drow / High / Wood), Gnome (Forest / Rock),
Goliath, Halfling, Human, Orc, Tiefling (Abyssal / Chthonic / Infernal).**

Out of scope: the four backgrounds in the PDF (Acolyte, Criminal, Sage, Soldier). They are
already in `character_class.hpp` (`BackgroundDef` table) and need no work.

## Where we start

- **Species today.** `Agent::Stats::species` is a string. `setSpecies()` in `agent.hpp`
  hard-codes Dhampir: it applies Speed 35, Darkvision 60 and Necrotic Resistance, and strips them
  on a swap by guessing (`if speed_walk == 35`). `dialogs.py` has `SPECIES = ["NONE", "Dhampir"]`.
  `tools/import_character.py` maps only Dhampir. `speciesNecroticMult()` sets the floor that
  Rage restores Necrotic Resistance to.
- **Primitives that already exist:** `darkvision_range`, `blindsight_range`, `speed_fly`,
  `magic_damage_multipliers` and the physical multipliers, `save_advantage_mask`,
  `condition_immunities`, `temp_hp`, `teleportAgent` (Misty Step), Topple (Prone on hit),
  Lucky `luck_points`, Tough (HP folded into `hp_max`), the `feats` vector, the Cunning Action
  bonus Dash, Hide/`hidden`, cone and line AoE geometry for spells, Enlarge (`size_damage_dice`),
  and the reaction windows (on-damaged, on-hit).
- **Missing:**
  - advantage on saves against a *specific condition* (Charmed, Frightened, Poisoned);
  - a "granted spell" record: always prepared, one free cast per Long Rest or PB casts, its own
    casting ability;
  - Heroic Inspiration;
  - reroll a natural 1;
  - Tremorsense;
  - a PC size category (Small / Medium / Large);
  - Relentless Endurance's 0-HP intercept, which exists only as Barbarian Relentless Rage;
  - a Breath Weapon that replaces one attack of the Attack action;
  - the Goliath ancestry riders;
  - engine effects for these spells: Hellish Rebuke, Pass without Trace, Faerie Fire,
    Detect Magic, and the utility cantrips.

## Step 0 — decisions (FROZEN 2026-11-24)

- **D1 Table-driven species.** Replace the Dhampir `if` chain with a `SpeciesDef` table in a new
  `species.hpp`. Each entry gives the base Speed, Darkvision, size options, damage resistances,
  save-advantage bits and flags. `setSpecies(name, option)` strips the old species *by its own
  definition*: subtract exactly what was applied, recorded in a small `species_applied` struct
  that is saved with the agent. No more value guessing. Dhampir moves into the table, and its
  save format stays compatible.
  **Implemented 2026-11-24 (uncommitted, 287/0).** `gui/species.hpp` holds `SpeciesDef`,
  `kSpeciesTable` (Dhampir only so far) and `SpeciesApplied {speed_from/to, darkvision_from/to,
  magic_resist_mask, save_advantage_bits}`. The strip puts a field back to its `_from` value
  only while it still holds the `_to` value, so a hand edit since then wins. `restore_species()`
  rebuilds the record for saves from before D1. `species_applied` is saved in the agent JSON and
  in the board snapshot. `speciesNecroticMult()` became `speciesMagicMult(type)`. The Stats
  dialog's `SPECIES` list now comes from `rpg.species_names()`.
- **D2 Sub-choices.** One `species_option` string carries the dragon colour, the Elven lineage,
  the Gnomish lineage, the Giant ancestry or the Fiendish legacy. `species_size` handles Human
  and Tiefling (Small or Medium). `species_spell_ability` (INT, WIS or CHA) applies to Elf, Gnome
  and Tiefling. All are picked in the Stats dialog next to Species.
- **D3 Granted spells.** A generic `GrantedSpell {name, unlock_level, free_uses_max, free_used,
  recharge (LR), ability}` vector on Stats. It is filled by species now and can be reused later
  by Magic Initiate and Fey Touched. Cantrips are always available. A leveled spell gets its free
  casts and can also be cast with slots when the PC has them. The free cast goes through the
  existing spell-cast path with a "no slot" flag, the way enspelled items do.
- **D4 Spells with no engine effect** (Detect Magic, Pass without Trace, Speak with Animals,
  Druidcraft, Prestidigitation, Mending, Minor Illusion, Dancing Lights, Thaumaturgy): they are
  listed on the sheet and castable as flavor. They are logged and use up their free use, with no
  mechanics. **Hellish Rebuke** and **Faerie Fire** get real effects in SP6 because they matter
  in combat. Everything else in the Elf and Tiefling tables needs an audit in SP0.
- **D5 Condition-save advantage.** Add `condition_save_adv`, a list of condition names on Stats.
  Brave (Frightened), Fey Ancestry (Charmed) and Dwarven Resilience (Poisoned) use it. It is
  consulted wherever a save "to avoid or end" a condition is rolled. Gnomish Cunning uses the
  existing `save_advantage_mask` (INT, WIS and CHA bits).
- **D6 Size.** Add a PC `size_category` (Small, Medium or Large). Small has no direct combat
  effect in 2024, but Hill's Tumble, Halfling Nimbleness, Naturally Stealthy and Large Form all
  read it. **Large Form takes a 2×2 footprint** (user, 2026-11-24). When it starts, the PC needs
  room to grow; if there is none, it is refused. When it ends, the PC shrinks back to the
  top-left cell.
- **D7 Breath Weapon.** An entry in the attack list that replaces one attack of the Attack action.
  Shape is a 15-ft cone or a 30×5-ft line, chosen on each use. Each creature in the area makes a
  DEX save against DC 8 + CON mod + PB. Damage is 1d10, 2d10 at level 5, 3d10 at 11 and 4d10 at
  17, half on a save. PB uses per Long Rest. It is built as a synthetic Spell record so the
  existing cone and line targeting does the work.
- **D8 Draconic Flight (level 5).** A bonus action sets `speed_fly = speed_walk` for 100 rounds.
  It ends early on Incapacitated or when dismissed (a free toggle). Once per Long Rest.
- **D9 Goliath Giant Ancestry.** One ancestry, PB uses per Long Rest, shared across its benefit.
  - Fire's Burn (+1d10 Fire), Frost's Chill (+1d6 Cold and −10 Speed) and Hill's Tumble (Prone
    on a Large-or-smaller target) are offered after an attack hits and deals damage, like the
    maneuver prompt.
  - Cloud's Jaunt is a bonus-action teleport of 30 ft.
  - Stone's Endurance (reaction: reduce damage by 1d12 + CON mod) and Storm's Thunder (reaction:
    1d8 Thunder to an attacker within 60 ft) use the on-damaged reaction window.
- **D10 Luck (Halfling).** An automatic reroll of a natural 1 on any d20 Test: attack, save or
  ability check. It applies in auto mode only. In real-dice mode the player rerolls at the
  table (user, 2026-11-24).
- **D11 Heroic Inspiration (user, 2026-11-24: Option B).** `heroic_inspiration` is a bool on
  Stats. A Human gets it back on each Long Rest. A PC holds at most one.
  - **Tracking.** A ★ badge appears on the PC sheet and in the initiative tracker. The DM can click
    the ★ to award or spend it, for any PC, since DM awards are allowed.
  - **Auto-mode prompt.** When a PC with the ★ misses an attack or fails a save, the engine sets
    `heroic_reroll_available` and the panel shows a "Use Heroic Inspiration? Reroll" button. This
    copies the `reckless_reroll_available` / Curving Shot pattern. Spending it rerolls the d20,
    the new roll stands, and the ★ is cleared.
  - **Limits.** Only attack and save d20s are prompted. Damage dice and ability checks stay with
    the DM by hand.
  - **Real-dice mode.** Tracking only. The player rerolls at the table and the DM clicks the ★.
- **D12 Skills.** Only Stealth, Perception, Sleight of Hand and Athletics are modelled. Keen Senses
  sets Perception. For Skillful, the picker offers the four modelled skills. Anything else is
  flavor.
- **D13 Versatile (Human).** A second origin-feat slot in the Stats dialog. The `feats` vector
  already holds more than one feat.
- **D14 Deferred (→ `known_limitations.md`):**
  - Trance, apart from immunity to magical sleep, which is cheap if Sleep is implemented;
  - Stonecunning Tremorsense (user, 2026-11-24: too much engine work);
  - Rock Gnome clockwork devices;
  - High Elf's cantrip swap on a Long Rest (a picker change only);
  - Powerful Build carrying capacity;
  - Halfling Nimbleness (user, 2026-11-24: too much engine work);
  - Naturally Stealthy, if the Hide rules do not have cover from a creature.

## Steps

Per-step loop: implement → `./test.sh` in the container → fix → commit on request → handoff.

- **SP0 — Audit.** Check every spell the species grant against `spells.json` and the engine, and
  record which ones work, which are data-only and which are missing. Confirm where the
  condition-save rolls happen for D5. No code changes.
- **SP1 — Species framework.** `species.hpp` with `SpeciesDef`, option, size and spell ability
  (D1, D2). `species_applied` strip and apply. Dhampir migrated onto it, with
  `test_dhampir.py` unchanged and green. Serialization and bindings. Species, option, size and
  ability pickers in the Stats dialog. The `speciesNecroticMult()` logic is generalized to "the
  species' resistance floor" for every damage type.
  **Done 2026-11-24 (288/0).** The table holds the nine SRD species after Dhampir, with
  `option_label`/`options`, `size_options` and the `kSpeciesSpellAbility` flag. Their traits are
  still zero, and SP2 fills them in. Stats gains `species_option`, `species_size` ("Small"/"Medium") and
  `species_spell_ability` (SaveAbility ordinal). `setSpecies(name, option = "")` and
  `normalizeSpeciesChoices` keep them valid, and `setSpeciesSize`/`setSpeciesSpellAbility` refuse
  invalid picks. All three are serialized, in the agent JSON and the snapshot, and older saves get
  the defaults. The Stats dialog has an option row and a Size + Spell Ability row (DLG_H 980).
  `test_species.py` is new. `test_dhampir.py` loses only its two exact-table-list asserts.
- **SP2 — Passive traits.**
  - Darkvision 60 or 120.
  - Speed 35 for Goliath and Wood Elf.
  - Resistances: Dragonborn by colour, Dwarf Poison, Tiefling by legacy.
  - `condition_save_adv` (D5) for Brave, Fey Ancestry and Dwarven Resilience.
  - Gnomish Cunning.
  - Dwarven Toughness: +1 HP per level, folded into `hp_max` and made idempotent the way Tough is.
  - Keen Senses: Perception.
  - Powerful Build: advantage on checks to escape a grapple.

  The whole of Dwarf, Gnome (minus spells) and most of Elf are done at this step.
  **Done 2026-11-24 (289/0).** `kSpeciesTable` carries each species' Speed, Darkvision,
  resistance and save bits; `kSpeciesOptionTable` adds the option's (Drow Darkvision 120, Wood
  Elf Speed 35, Draconic and Fiendish resistance), merged by `speciesTraits(def, option)`.
  `SpeciesApplied` gains `hp_bonus` (Dwarven Toughness, kept equal to `char_level` by
  `syncSpeciesHp()`, which the Stats dialog calls after a level change) and `perception_prof`
  (Keen Senses; cleared on a swap only if it set it). D5: `Stats::condition_save_adv` is a list
  for other sources; the species' own (Brave, Fey Ancestry, Dwarven Resilience) are flags read
  live by `hasConditionSaveAdv`, never stored. `CombatEngine::conditionSaveAdvantage` replaces
  every `beguilingTwistAdvantage` call site and fills the three SP0 gaps: the weapon on-hit
  rider save (which now also reads `saveAdvantageFor` and curse Disadvantage), the skip-turn
  save loop, and `rollFixedDcSave` (new optional `condition_name`). Powerful Build: Advantage on
  both grapple-escape checks. `restoreSpecies(name, option)` re-derives Darkvision and Keen
  Senses with the option. New suite `test_species_traits.py`. A species picked in an SP1-era
  save got no traits; re-pick it to apply them.
- **SP3 — Granted spells (D3).** The `GrantedSpell` vector, Long Rest recharge and the
  free-cast path. Elf lineage cantrips plus level 3 and 5 spells, Forest Gnome, Rock Gnome
  cantrips, Tiefling legacy plus Thaumaturgy. The spell dialog shows them with "free ×N" or a slot
  choice. Tests cover unlock levels, the free cast, recharge and the casting ability.
  **Done 2026-11-25 (290/0).** `species.hpp` adds `GrantedSpell {name, source, unlock_level,
  uses (0 cantrip, N per Long Rest, -1 = PB), free_used, ability}` and `kSpeciesSpellTable`
  (option "" = every option, for Thaumaturgy). `Stats::granted_spells` is rebuilt by
  `syncSpeciesSpells()` from `setSpecies` / `restoreSpecies` (free_used kept for a spell that
  stays, other sources' entries kept); `setSpeciesSpellAbility` re-tags the species' entries.
  Unlock is read live against `char_level`. Payment is by name (`grantedSpell(name)`), so a
  same-named class spell gets the free casts and ability too. `SpellAction::use_grant` spends a
  free cast at base level, with no slot and no one-slot-spell mark; refused when none is left. A
  PC's plain cast with no slot for it falls back to the free cast (automation passes slot 0),
  and so does the automated teleport path. The cast swaps `spellcasting_ability` to the grant's
  for the whole of `executeSpell` (RAII guard, by caster index) — a stopgap until MC5's
  per-spell ability helpers. `availableCastableSpells` lists a leveled grant with a free cast
  left, outside the one-slot rule. Long Rest refills. Python: `Spell.granted` tags the list
  entries, which `helpers.sync_item_spells` now derives along with item spells (skipping a name
  the creature already knows), so every existing sync call site covers them; the Stats dialog
  OK syncs too. They are left out of `spell_indices`; `granted_spells` is saved in the agent
  JSON and the snapshot. The cast menu adds a "free ×N" row ahead of the slot rows (those still
  honour the one-slot rule). New suite `test_species_spells.py`.
- **SP4 — Halfling, Orc and Human.**
  - Luck (D10).
  - Adrenaline Rush: bonus-action Dash plus PB temp HP, PB uses per Short or Long Rest.
  - Relentless Endurance: share the Relentless Rage 0-HP intercept, once per Long Rest.
  - Heroic Inspiration (D11).
  - Skillful (D12) and the second origin feat (D13).
  **Done 2026-11-25 (292/0).** New species flags (Luck, Adrenaline, Relentless, Heroic,
  Skillful, Versatile) and Stats fields `species_skill`, `adrenaline_rush_used`,
  `relentless_endurance_used`, `heroic_inspiration` (agent JSON, snapshot, PC play state).
  Luck: `CombatEngine::d20Test` / `d20TestFor` reroll each natural-1 die once; wired into the
  weapon and spell attack rolls, spell saves (incl. condition and save-for-half), the weapon
  rider save, the turn-start/end repeat saves, Aura-of-Dread style Frightened saves,
  concentration, `rollFixedDcSave`, trap/item saves, shove/grapple contests, the grapple
  escape, death saves and Initiative. The rarer per-feature d20s still roll flat (listed in
  known_limitations). Adrenaline Rush is a Bonus-band button (`use_adrenaline_rush`: Dash +
  PB temp HP, the larger kept; Short Rest refills). Relentless Endurance auto-fires in
  `damageAgent` after Relentless Rage. Heroic Inspiration: a Human gets it on pick and each
  Long Rest; a miss with it held sets `heroic_reroll_available` (GUI prompt →
  `apply_heroic_reroll`); a failed spell save offers "HeroicInspiration" in the OnSaveFail
  window. ★/☆ toggle on tracker rows (PCs or holders), ★ after the name in the engine-mode
  initiative list. Skillful is read live by the skill helpers (no fold-in). Versatile: the
  Stats dialog's Human rows are Size + Skill and a Versatile origin-feat picker;
  `set_origin_feat` takes the second feat and strips/applies both. Suite
  `test_species_sp4.py`.
- **SP5 — Dragonborn.** Breath Weapon (D7) as an attack-list entry with the shape chosen per
  use. Draconic Flight (D8). Tests for the DC, scaling dice, half damage, the use count and the
  flight lapsing on Incapacitated.
- **SP6 — Goliath, plus the combat spells left over.** Giant Ancestry (D9): on-hit prompt,
  bonus-action teleport, the two reactions. Large Form (D6): bonus action, Large, +10 Speed,
  advantage on STR checks, 100 rounds, once per Long Rest. Hellish Rebuke and Faerie Fire
  engine effects, if SP0 shows they are missing. SP0 showed both are missing; fix the
  Faerie Fire record too. **Chill Touch's no-heal rider is built here as well** (user,
  2026-11-24: it should have existed already).
- **SP7 — Import, NPC and docs.** `tools/import_character.py` maps the D&D Beyond race and
  subrace to species and option. Random party generation (`party_gen.py`) can roll species.
  `known_limitations.md` gets the D14 list. Update `memory/` architecture notes.
- **SP8 — Live check.** Do a `run.sh` pass with one PC of each species, then close the plan.

## SP0 audit results (2026-11-24)

**Spells.** All 21 species spells exist in `spells.json`.

| Status | Spells |
|---|---|
| Works in the engine, tested | Fire Bolt, Poison Spray (attack + tier dice), Misty Step, Darkness (`light_level` 4, magical), Longstrider, False Life (temp-HP pool), Hold Person, Ray of Enfeeblement, Ray of Sickness (Poisoned on hit) |
| Works, rider missing | **Chill Touch**: damage and scaling work, but "can't regain HP until the end of your next turn" has no engine primitive |
| Data only (D4 flavor) | Dancing Lights, Prestidigitation, Druidcraft, Minor Illusion, Mending, Thaumaturgy, Detect Magic, Speak with Animals, Pass without Trace. Each is a no-damage `Automatic` record, and casting it already resolves as a no-op |
| Missing (SP6) | **Hellish Rebuke**: the record is a plain action-cast DEX save for 2d10 Fire, with no reaction trigger and no `casting_time`. **Faerie Fire**: no engine effect, and the record is wrong: `AttackRoll` and a 15-ft Sphere, where it should be a DEX save in a 20-ft Cube |

Added to SP6: fix the Faerie Fire record, and build the Chill Touch no-heal rider (user,
2026-11-24).

**Condition saves (D5).** A condition-aware hook already exists:
`beguilingTwistAdvantage(bm, saver, condition_name)` (`combat_ranger.cpp:134`), Charmed/Frightened
only. D5 should generalize it into a `conditionSaveAdvantage(bm, saver, cond)` that also reads
`condition_save_adv`, and then call it at every site below.

- Already calls the hook: `rollSpellSave` (`combat_spells.cpp:444`), `executeSpell` condition
  saves (`:2337`), `applySpellEffect` save-for-half (`:3369`), the `beginTurn` repeat-save loop
  (`combat_turn.cpp:1049`), the `endTurn` save loop (`:1205`), and the hard-coded Frightened and
  Charmed sites: Aura of Courage/Dread (`combat_turn.cpp:336`), Intimidating Presence
  (`combat_barbarian.cpp:551`), Fighter (`combat_fighter.cpp:192`, `:664`), Ranger
  (`combat_ranger.cpp:111`, `:200`), Beguiling Magic (`combat_bard.cpp:307`).
- **Gaps:**
  - The weapon on-hit condition save (`applyAttackResult`, `combat_attack.cpp:4705`) rolls a
    flat d20 with no advantage logic at all, not even `saveAdvantageFor`. This is the main path
    for monster **Poisoned** riders (5 in `DND2024_MonsterStats.json`), so Dwarven Resilience
    needs it.
  - The skip-turn save loop in `beginTurn` (`combat_turn.cpp:940`) has no hook.
  - `rollFixedDcSave` (`combat_contested.cpp:269`, used by `lair.py`) takes no condition name.
- Not condition saves, so no change is needed: concentration, Counterspell, thrown items, Cunning
  Strike, Telekinetic, Elemental Burst, slipping terrain, Steps of the Fey, Clairvoyant
  Combatant, delayed effects.

## Rules constants

| Species | Size | Speed | Darkvision | Resistance | Use pools |
|---|---|---|---|---|---|
| Dragonborn | M | 30 | 60 | by ancestry | Breath PB/LR; Flight 1/LR (L5) |
| Dwarf | M | 30 | 120 | Poison | Stonecunning PB/LR |
| Elf | M | 30 (Wood 35) | 60 (Drow 120) | — | lineage spells 1/LR each |
| Gnome | S | 30 | 60 | — | Speak with Animals PB/LR (Forest) |
| Goliath | M | 35 | — | — | Ancestry PB/LR; Large Form 1/LR (L5) |
| Halfling | S | 30 | — | — | — |
| Human | S/M | 30 | — | — | Heroic Inspiration 1/LR |
| Orc | M | 30 | 120 | — | Adrenaline PB/SR; Relentless 1/LR |
| Tiefling | S/M | 30 | 60 | by legacy | legacy spells 1/LR each |

Draconic resistance by ancestry: Black and Copper Acid, Blue and Bronze Lightning, Brass, Gold and
Red Fire, Green Poison, Silver and White Cold.
