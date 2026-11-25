---
name: architecture-species
description: How species work end to end — species.hpp tables, set/restore_species, granted spells, the species pools, and where import/generation feed in (SPECIES_PLAN.md)
metadata:
  type: project
---

# Species (SPECIES_PLAN.md, SP1–SP7, 2026-11-24/25)

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

**Sub-choices** (`species_option`, `species_size`, `species_spell_ability`, `species_skill`)
are normalized by `normalize_species_choices`; an invalid pick falls back to the default.

**Granted spells** (`GrantedSpell`, `granted_spells`, `sync_species_spells`) are always
prepared, carry their own free-use count and casting ability, and are reusable by future
feats (Magic Initiate, Fey Touched) via a non-"species" `source`.

**Per-species pools** live on Stats (`breath_weapon_used`, `adrenaline_rush_used`,
`relentless_endurance_used`, Large Form, Giant Ancestry, `heroic_inspiration`, Luck via
`d20Test`) and reset on a Long Rest.

Deferred traits and the import/generator limits: [[known-limitations]] → "Species".
