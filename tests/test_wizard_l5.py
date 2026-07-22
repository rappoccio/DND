#!/usr/bin/env python3
"""
Test Wizard L5 mechanics: Memorize Spell
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_memorize_spell_resource_at_l5():
    """Verify Memorize Spell resource is created at L5"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Wizard5", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 5
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 5)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert "Memorize Spell" in stats.resources, "Wizard L5 should have Memorize Spell resource"

    ms = stats.resources["Memorize Spell"]
    assert ms.current == 1, f"Memorize Spell should have 1 use, got {ms.current}"
    assert ms.max == 1, "Memorize Spell max should be 1"
    print("✅ test_memorize_spell_resource_at_l5 passed")


def test_memorize_spell_not_at_l4():
    """Verify Memorize Spell resource is NOT created at L4"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Wizard4", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 4
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 4)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert "Memorize Spell" not in stats.resources, "Wizard L4 should NOT have Memorize Spell resource"
    print("✅ test_memorize_spell_not_at_l4 passed")


def test_memorize_spell_restores_on_short_rest():
    """Verify Memorize Spell restores on short rest"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Wizard5", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 5
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 5)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    ms = stats.resources["Memorize Spell"]
    assert ms.short_rest_regen == 1, f"Memorize Spell should restore 1 use on short rest, got {ms.short_rest_regen}"
    print("✅ test_memorize_spell_restores_on_short_rest passed")


def test_memorize_spell_restores_on_long_rest():
    """Verify Memorize Spell restores on long rest"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Wizard5", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 5
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 5)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    ms = stats.resources["Memorize Spell"]
    assert ms.long_rest_regen == 1, f"Memorize Spell should restore 1 use on long rest, got {ms.long_rest_regen}"
    print("✅ test_memorize_spell_restores_on_long_rest passed")


if __name__ == "__main__":
    tests = [
        test_memorize_spell_resource_at_l5,
        test_memorize_spell_not_at_l4,
        test_memorize_spell_restores_on_short_rest,
        test_memorize_spell_restores_on_long_rest,
    ]

    print("Running Wizard L5 Tests...")
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
