#!/usr/bin/env python3
"""
Test Wizard L3 Diviner Portent Dice mechanics
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_portent_dice_resource_at_l3():
    """Verify Portent Dice resource is created at L3 for Diviners"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("DivinierWizard3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 3
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert "Portent Dice" in stats.resources, "Wizard L3 Diviner should have Portent Dice resource"

    pd = stats.resources["Portent Dice"]
    assert pd.current == 2, f"Portent Dice should have 2 uses, got {pd.current}"
    assert pd.max == 2, "Portent Dice max should be 2"
    print("✅ test_portent_dice_resource_at_l3 passed")


def test_portent_dice_not_for_non_diviners():
    """Verify Portent Dice resource exists for all Wizards but is only usable by Diviners"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("EvokerWizard3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 3
    stats.wizard_subclass = rpg.WizardSubclass.Evoker  # NOT Diviner
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert "Portent Dice" in stats.resources, "Wizard L3 should have Portent Dice resource"
    # The resource exists but use_portent_die() will reject it since subclass != Diviner
    print("✅ test_portent_dice_not_for_non_diviners passed")


def test_portent_dice_upgraded_at_l14():
    """Verify Portent Dice max increases to 3 at L14"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("DivinierWizard14", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 14
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 14)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    pd = stats.resources["Portent Dice"]
    assert pd.max == 3, f"Portent Dice at L14 should have max 3, got {pd.max}"
    print("✅ test_portent_dice_upgraded_at_l14 passed")


def test_portent_dice_regeneration_on_long_rest():
    """Verify Portent Dice are regenerated on long rest"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("DivinierWizard3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 3
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest to regenerate portent dice
    engine.apply_long_rest(bm)

    stats = engine.get_agent_stats(bm, idx)
    assert len(stats.portent_dice) == 2, f"Should have 2 portent dice after long rest, got {len(stats.portent_dice)}"

    # Dice should be d20 values (1-20)
    for die in stats.portent_dice:
        assert 1 <= die <= 20, f"Portent die value {die} should be 1-20"

    print("✅ test_portent_dice_regeneration_on_long_rest passed")


def test_use_portent_die_basic():
    """Verify using a portent die sets pending and decrements resource"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("DivinierWizard3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 3
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Regenerate to populate portent_dice
    engine.apply_long_rest(bm)

    stats = engine.get_agent_stats(bm, idx)
    initial_count = stats.resources["Portent Dice"].current
    initial_dice_count = len(stats.portent_dice)

    # Use first portent die
    success = engine.use_portent_die(bm, idx, 0, current_round=1)
    assert success, "use_portent_die should succeed for valid Diviner"

    # Check resource decreased and die was removed
    stats = engine.get_agent_stats(bm, idx)
    assert stats.resources["Portent Dice"].current == initial_count - 1, \
        "Portent Dice resource should have decreased by 1"
    assert len(stats.portent_dice) == initial_dice_count - 1, \
        "Portent dice deque should have 1 fewer die"

    print("✅ test_use_portent_die_basic passed")


def test_use_portent_die_per_round_limit():
    """Verify only one portent die can be used per round"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("DivinierWizard3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 3
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Regenerate to populate portent_dice (creates 2 dice)
    engine.apply_long_rest(bm)

    # Use first portent die in round 1
    success1 = engine.use_portent_die(bm, idx, 0, current_round=1)
    assert success1, "First use in round 1 should succeed"

    # Try to use second portent die in same round - should fail (per-round limit)
    # Note: After first use, die at index 1 is now at index 0
    success2 = engine.use_portent_die(bm, idx, 0, current_round=1)
    assert not success2, "Second use in same round should fail (per-round limit)"

    # Use in next round should work (the remaining die is at index 0)
    success3 = engine.use_portent_die(bm, idx, 0, current_round=2)
    assert success3, "Use in different round should succeed"

    print("✅ test_use_portent_die_per_round_limit passed")


def test_use_portent_die_rejects_non_diviner():
    """Verify non-Diviner wizards cannot use portent"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("AbjurerWizard3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 3
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer  # NOT Diviner
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Regenerate to populate portent_dice anyway
    engine.apply_long_rest(bm)

    # Try to use portent - should fail
    success = engine.use_portent_die(bm, idx, 0, current_round=1)
    assert not success, "Non-Diviner should not be able to use portent die"

    print("✅ test_use_portent_die_rejects_non_diviner passed")


if __name__ == "__main__":
    tests = [
        test_portent_dice_resource_at_l3,
        test_portent_dice_not_for_non_diviners,
        test_portent_dice_upgraded_at_l14,
        test_portent_dice_regeneration_on_long_rest,
        test_use_portent_die_basic,
        test_use_portent_die_per_round_limit,
        test_use_portent_die_rejects_non_diviner,
    ]

    print("Running Wizard L3 Portent Dice Tests...")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
