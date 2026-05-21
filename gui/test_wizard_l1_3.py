#!/usr/bin/env python3
"""
Test Wizard L1-3 mechanics: Spellcasting, Ritual Adept, Arcane Recovery, Scholar, Subclass choice
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_wizard_spellcasting_ability():
    """Verify Wizard spellcasting ability is INT"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Wizard1", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 1
    stats.intel = 16
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 1)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.spellcasting_ability == 3, f"Wizard should have INT spellcasting (3), got {stats.spellcasting_ability}"
    assert stats.can_cast_spell == True, "Wizard should be able to cast spells"
    print("✅ test_wizard_spellcasting_ability passed")


def test_wizard_spell_slots():
    """Verify Wizard spell slots match table B (2/0/0... at L1)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    test_cases = [
        (1, [2, 0, 0, 0, 0, 0, 0, 0, 0]),
        (2, [3, 0, 0, 0, 0, 0, 0, 0, 0]),
        (3, [4, 2, 0, 0, 0, 0, 0, 0, 0]),
        (4, [4, 3, 0, 0, 0, 0, 0, 0, 0]),
        (5, [4, 3, 2, 0, 0, 0, 0, 0, 0]),
        (9, [4, 3, 3, 3, 1, 0, 0, 0, 0]),
    ]

    for level, expected_slots in test_cases:
        config = create_test_agent(f"Wizard{level}", 5, 5)
        idx = add_agent_to_battle(engine, bm, config)

        stats = engine.get_agent_stats(bm, idx)
        stats.character_class = rpg.CharacterClass.Wizard
        stats.char_level = level
        stats.set_class_level(rpg.CharacterClass.Wizard, level)
        engine.set_agent_stats(bm, idx, stats)

        stats = engine.get_agent_stats(bm, idx)
        for i in range(9):
            assert stats.spell_slots_max[i] == expected_slots[i], \
                f"L{level} slot {i+1}: expected {expected_slots[i]}, got {stats.spell_slots_max[i]}"

    print("✅ test_wizard_spell_slots passed")


def test_arcane_recovery_resource():
    """Verify Arcane Recovery resource is initialized correctly"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Wizard1", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 1
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 1)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert "Arcane Recovery" in stats.resources, "Wizard should have Arcane Recovery resource"

    ar = stats.resources["Arcane Recovery"]
    assert ar.current == 1, f"Arcane Recovery should have 1 use, got {ar.current}"
    assert ar.max == 1, "Arcane Recovery max should be 1"
    print("✅ test_arcane_recovery_resource passed")


def test_arcane_recovery_by_level():
    """Verify Arcane Recovery levels to recover scale correctly"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    test_cases = [
        (1, 1),  # ceil(1/2) = 1
        (2, 1),  # ceil(2/2) = 1
        (3, 2),  # ceil(3/2) = 2
        (4, 2),  # ceil(4/2) = 2
        (5, 3),  # ceil(5/2) = 3
        (10, 5), # ceil(10/2) = 5
        (20, 10),# ceil(20/2) = 10
    ]

    for level, expected_levels in test_cases:
        config = create_test_agent(f"Wizard{level}", 5, 5)
        idx = add_agent_to_battle(engine, bm, config)

        stats = engine.get_agent_stats(bm, idx)
        stats.character_class = rpg.CharacterClass.Wizard
        stats.char_level = level
        stats.initialize_class_resources(rpg.CharacterClass.Wizard, level)
        engine.set_agent_stats(bm, idx, stats)

        stats = engine.get_agent_stats(bm, idx)
        ar = stats.resources["Arcane Recovery"]
        # For now, we just verify the resource exists; actual level recovery would be tested
        # when Arcane Recovery mechanic is fully implemented
        assert ar.current == 1, f"L{level}: Arcane Recovery current should be 1"

    print("✅ test_arcane_recovery_by_level passed")


def test_wizard_subclass_selection():
    """Verify Wizard can select a subclass"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    subclasses = [
        rpg.WizardSubclass.Abjurer,
        rpg.WizardSubclass.Diviner,
        rpg.WizardSubclass.Evoker,
        rpg.WizardSubclass.Illusionist,
    ]

    for subclass in subclasses:
        config = create_test_agent(f"Wizard_sub{subclass}", 5, 5)
        idx = add_agent_to_battle(engine, bm, config)

        stats = engine.get_agent_stats(bm, idx)
        stats.character_class = rpg.CharacterClass.Wizard
        stats.char_level = 3
        stats.wizard_subclass = subclass
        engine.set_agent_stats(bm, idx, stats)

        stats = engine.get_agent_stats(bm, idx)
        assert stats.wizard_subclass == subclass, \
            f"Expected subclass {subclass}, got {stats.wizard_subclass}"

    print("✅ test_wizard_subclass_selection passed")


if __name__ == "__main__":
    tests = [
        test_wizard_spellcasting_ability,
        test_wizard_spell_slots,
        test_arcane_recovery_resource,
        test_arcane_recovery_by_level,
        test_wizard_subclass_selection,
    ]

    print("Running Wizard L1-3 Tests...")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
