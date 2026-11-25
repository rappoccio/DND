# SRD Species — Plan

Drafted 2026-11-24. Source: `character_origins.pdf` (SRD 5.2, pp. 83–86). Status: **DRAFT —
Step 0 not frozen.** Nothing is implemented until D1–D14 are signed off.

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

## Step 0 — decisions (proposed, NOT frozen)

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
- **SP3 — Granted spells (D3).** The `GrantedSpell` vector, Long Rest recharge and the
  free-cast path. Elf lineage cantrips plus level 3 and 5 spells, Forest Gnome, Rock Gnome
  cantrips, Tiefling legacy plus Thaumaturgy. The spell dialog shows them with "free ×N" or a slot
  choice. Tests cover unlock levels, the free cast, recharge and the casting ability.
- **SP4 — Halfling, Orc and Human.**
  - Luck (D10).
  - Adrenaline Rush: bonus-action Dash plus PB temp HP, PB uses per Short or Long Rest.
  - Relentless Endurance: share the Relentless Rage 0-HP intercept, once per Long Rest.
  - Heroic Inspiration (D11).
  - Skillful (D12) and the second origin feat (D13).
- **SP5 — Dragonborn.** Breath Weapon (D7) as an attack-list entry with the shape chosen per
  use. Draconic Flight (D8). Tests for the DC, scaling dice, half damage, the use count and the
  flight lapsing on Incapacitated.
- **SP6 — Goliath, plus the combat spells left over.** Giant Ancestry (D9): on-hit prompt,
  bonus-action teleport, the two reactions. Large Form (D6): bonus action, Large, +10 Speed,
  advantage on STR checks, 100 rounds, once per Long Rest. Hellish Rebuke and Faerie Fire
  engine effects, if SP0 shows they are missing.
- **SP7 — Import, NPC and docs.** `tools/import_character.py` maps the D&D Beyond race and
  subrace to species and option. Random party generation (`party_gen.py`) can roll species.
  `known_limitations.md` gets the D14 list. Update `memory/` architecture notes.
- **SP8 — Live check.** Do a `run.sh` pass with one PC of each species, then close the plan.

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
