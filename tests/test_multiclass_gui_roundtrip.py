#!/usr/bin/env python3
"""
Multiclassing Phase 5 — GUI save/load round-trip.

Phase 5 wires the multiclass build (per-class levels + per-class subclasses)
through the existing stats save/OK path and the agent loader. The GUI dialog
itself is pygame and not unit-testable headlessly, but the data path it feeds is:

  * main.py serializes `agent_class_levels` ({class: level}) plus the independent
    per-class subclass fields (Phase 1).
  * agent_loader.restore_class_resources() reads that dict, sets the primary class
    (single-class reset) + the remaining classes additively, applies each subclass,
    then calls initialize_multiclass_resources() so resources MERGE across classes
    (Phase 5 changed this from the single-class initialize_class_resources).

These tests assert a saved multiclass agent restores all of: per-class levels, the
correct combined spell slots, each class's subclass, and the merged resources —
and that a legacy single-class save (no agent_class_levels) still loads identically.

Run standalone (asserts raise → non-zero exit) or via tests/run_all_tests.py.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from agent_loader import restore_class_resources

CC = rpg.CharacterClass


# ── Fighter 5 / Monk 5: both classes' features, one Extra Attack ───────────────────
def test_fighter_monk_multiclass_roundtrip():
    # Mirrors what main.py writes for a Fighter 5 (Champion) / Monk 5 build.
    saved = {
        "agent_class_levels": {"Fighter": 5, "Monk": 5},
        "agent_fighter_subclass": "Champion",
        "agent_monk_subclass": "WarriorOfTheOpenHand",
    }
    s = rpg.Stats()
    restore_class_resources(s, saved, rpg)

    assert s.class_level(CC.Fighter) == 5, f"Fighter level lost, got {s.class_level(CC.Fighter)}"
    assert s.class_level(CC.Monk) == 5, f"Monk level lost, got {s.class_level(CC.Monk)}"
    assert s.total_level() == 10, f"total level should be 10, got {s.total_level()}"
    # Primary mirror is the lowest-enum class (Fighter precedes Monk).
    assert s.character_class == CC.Fighter, f"primary should mirror Fighter, got {s.character_class}"

    names = set(s.resources.keys())
    assert "Second Wind" in names, f"Fighter's Second Wind missing: {sorted(names)}"
    assert "Action Surge" in names, f"Fighter's Action Surge missing: {sorted(names)}"
    assert "Focus Points" in names, f"Monk's Focus Points missing: {sorted(names)}"
    # Both classes grant Extra Attack at 5, but it must not stack.
    assert s.num_attacks == 2, f"one Extra Attack expected (num_attacks=2), got {s.num_attacks}"
    # Each class's subclass survives independently.
    assert s.fighter_subclass == rpg.FighterSubclass.Champion
    assert s.monk_subclass == rpg.MonkSubclass.WarriorOfTheOpenHand
    print("✅ test_fighter_monk_multiclass_roundtrip passed")


# ── Cleric 3 / Wizard 3: combined full-caster slots, not two level-3 tables ─────────
def test_cleric_wizard_combined_slots_roundtrip():
    saved = {
        "agent_class_levels": {"Cleric": 3, "Wizard": 3},
        "agent_cleric_subclass": "LifeDomain",
        "agent_wizard_subclass": "Evoker",
    }
    s = rpg.Stats()
    restore_class_resources(s, saved, rpg)

    assert s.class_level(CC.Cleric) == 3 and s.class_level(CC.Wizard) == 3
    assert s.total_level() == 6
    # Combined caster level 6 (3 full + 3 full) → the level-6 full-caster row: 4/3/3.
    slots = list(s.spell_slots_max)
    assert slots[0] == 4 and slots[1] == 3 and slots[2] == 3, \
        f"Cleric3/Wizard3 should have combined 4/3/3 slots, got {slots[:3]}"
    # Not two separate level-3 tables (which would be 4/2, no 3rd-level slot).
    assert slots[2] > 0, "combined caster should have a 3rd-level slot"
    assert s.cleric_subclass == rpg.ClericSubclass.LifeDomain
    assert s.wizard_subclass == rpg.WizardSubclass.Evoker
    print("✅ test_cleric_wizard_combined_slots_roundtrip passed")


# ── Legacy single-class save (no agent_class_levels) still loads ───────────────────
def test_legacy_single_class_roundtrip():
    saved = {
        "agent_class": "Barbarian",
        "agent_char_level": 5,
        "agent_barbarian_subclass": "Berserker",
    }
    s = rpg.Stats()
    restore_class_resources(s, saved, rpg)

    assert s.class_level(CC.Barbarian) == 5
    assert s.total_level() == 5
    assert s.character_class == CC.Barbarian
    assert "Rage" in s.resources, "legacy Barbarian must still get Rage"
    assert s.barbarian_subclass == rpg.BarbianSubclass.Berserker
    print("✅ test_legacy_single_class_roundtrip passed")


if __name__ == "__main__":
    test_fighter_monk_multiclass_roundtrip()
    test_cleric_wizard_combined_slots_roundtrip()
    test_legacy_single_class_roundtrip()
    print("\n✅ All multiclass GUI round-trip tests passed!")
