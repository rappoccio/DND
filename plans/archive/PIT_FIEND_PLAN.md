# STATUS: ✅ DONE (2026-07) — build + test_pit_fiend.py (8 tests) + full suite GREEN

Implemented: generic DoT/no-heal condition rider (dot_dice/prevents_healing→cant_heal, ticked
in beginTurn) + Magic Resistance (Stats.magic_resistance in rollSpellSave) + PitFiendFearAura &
Hellfire spells + rebuilt Pit Fiend record (Bite poison / 2× Devilish Claw / Fiery Mace,
multiattack [[0,1],[1,2],[2,1]]). Fear-Aura approximates "immune after save" as a per-turn
re-save (Balor Fire-Aura parity). See memory pit_fiend_implementation.md.

--- original plan ---

Fear aura: 20 foot emanation, WIS Save, DC 21, or enemy is Frightened of the pit fiend. If it saves, it is immune to the fear aura. 

Legendary resistances: 4 / day

Magic resistance: Advantage on saving throws against spells and other magical effects 

Multiattack: one Bite, two Devilish Claw, one Fiery Mace attacks per turn

Bite: reach 10 feet, 3d6+8 piercing damage, and must make a CON save (DC21) or has the Poisoned condition, where it cannot regenerate hit points and takes 6d6 Poison Damage at the start of each of its turns. Repeats save each turn, ends the condition on success. 

Devilish Claw: reach 10 feet, 4d8+8 necrotic damage

Fiery Mace: 10 feet, 4d6+8 force damage and 6d6 fire damage

Hellfire spellcasting: recharges 5-6 turns. Cast one of:  Fireball (level 7 version) with spell save DC 21 (charisma is its spellcasting ability), Hold Monster (Level 7 version), or Wall of Fire. 