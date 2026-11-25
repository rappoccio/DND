---
name: architecture-species
description: How species work end to end — species.hpp tables, set/restore_species, granted spells, the species pools, and where import/generation feed in (SPECIES_PLAN.md, MORE_SPECIES_PLAN.md)
metadata:
  type: project
---

# Species (SPECIES_PLAN.md SP1–SP7; MORE_SPECIES_PLAN.md MS1–MS6; 2026-11-24/25)

Sixteen species: Dhampir, the nine SRD species, and Aasimar, Hexblood, Lupin, Reborn,
Bugbear and Fairy (Bugbear/Fairy from Monsters of the Multiverse, ASIs and languages ignored).

**Data is a table, not code.** `gui/species.hpp` holds `kSpeciesTable` (one `SpeciesDef` per
species: Speed, Darkvision, size options, resistances, save-advantage bits, feature flags,
option list), `kSpeciesOptionTable` (what a lineage / ancestry / legacy adds) and
`kSpeciesSpellTable` (granted spells by species + option + unlock level). `speciesTraits(def,
option)` merges the first two. A new species or option is a table row; a new *mechanic* is a
flag bit plus the engine code that reads it.

**Two ways in, on `Agent::Stats`:**
- `set_species(name, option)` — the dialog path. Strips the old species by its own
  `SpeciesApplied` record (only fields that still hold what it set), then applies the new
  one: Speed (max), Darkvision (max), resistances, save bits, Dwarven Toughness HP, Keen
  Senses. Use it whenever a species *changes*.
- `restore_species(name, option)` — the load path (`agent_loader.py`). Assumes Speed and HP
  are already folded into the saved numbers; re-derives Darkvision, resistances, save bits
  and Perception, and rebuilds `species_applied`. Saved files, D&D Beyond imports
  (`tools/import_character.map_species`) and generated PCs (`party_gen.build_pc(species=)`)
  all go through it, so the importer takes Speed/HP from DDB and the generator folds them in
  itself.

**Folded-in traits besides Speed/HP.** A Fey creature type (Hexblood, Fairy) is saved as
`is_fey`, Fairy Flight as `speed_fly`; `restore_species` records both in `species_applied`
(`fey`, `fly_from`/`fly_to`) so a species change strips only what it set. Fairy Flight is
grounded by Medium/Heavy armor: `BattleMap::setAgentArmor` sets `armor_medium_heavy` and
calls `syncSpeciesFlight`.

**Sub-choices** (`species_option`, `species_size`, `species_spell_ability`, `species_skill`)
are normalized by `normalize_species_choices`; an invalid pick falls back to the default.
`SpeciesDef.skill_options` overrides the skill list (Lupin: Perception/Stealth/Survival;
Reborn and Human: the four modelled skills). Reborn's option is its Strange Endurance
resistance.

**Granted spells** (`GrantedSpell`, `granted_spells`, `sync_species_spells`) are always
prepared, carry their own free-use count and casting ability, and are reusable by future
feats (Magic Initiate, Fey Touched) via a non-"species" `source`.

**Per-species pools** live on Stats (`breath_weapon_used`, `adrenaline_rush_used`,
`relentless_endurance_used`, Large Form, Giant Ancestry, `heroic_inspiration`, Luck via
`d20Test`) and reset on a Long Rest.

**MORE_SPECIES mechanics** (each a flag bit in `kSpeciesTable`):
- Aasimar: Healing Hands (Magic action, PB d4, 1/LR; tracker button HH) and Celestial
  Revelation (L3, 1/LR, 10 rounds: Heavenly Wings / Inner Radiance / Necrotic Shroud, +PB
  damage once per turn; Shroud's Frightened uses `ActiveAgentCondition::ends_at_caster_turn_end`).
- Hexblood / Fairy: Fey type and granted spells (Disguise Self, Hex; Druidcraft, Faerie Fire,
  Enlarge/Reduce). `SpellAction.enlarge` is the Enlarge/Reduce mode picker for every caster.
- Lupin: Howl (Bonus Action, PB/LR, WIS save or `howled_by`) and Feral Pounce (Slashing
  Unarmed Strikes, a Shove after an Unarmed hit, once per turn).
- Reborn: death-save Advantage and Knowledge from a Past Life (a d6 on a failed engine roll).
- Bugbear: Long-Limbed (+5 ft melee reach on its own turn only; OA scans untouched) and
  Surprise Attack (once per combat vs a creature that hasn't taken a turn; the flag re-arms
  in `app_initiative.start_combat`).

**Import and generation.** `tools/import_character.SPECIES_OPTIONS` and
`gui/party_gen.SPECIES` each mirror the table (party_gen leaves Dhampir out);
`test_species_import.py` checks both against DDB sources and loads every species/option.

Deferred traits and the import/generator limits: [[known-limitations]] → "Species".
