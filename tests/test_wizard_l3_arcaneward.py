#!/usr/bin/env python3
"""
Test Abjurer Wizard Arcane Ward mechanics (L3+)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_arcane_ward_long_rest_initialization():
    """Verify Arcane Ward initializes to char_level on long rest"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Abjurer3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config, intel=16)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer
    stats.char_level = 3
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest
    engine.apply_long_rest(bm)

    # Verify temp_hp = char_level (3)
    stats = engine.get_agent_stats(bm, idx)
    assert stats.temp_hp == 3, f"Arcane Ward should be 3, got {stats.temp_hp}"
    print("✅ test_arcane_ward_long_rest_initialization passed")


def test_arcane_ward_not_initialized_below_l3():
    """Verify Arcane Ward is NOT initialized for Abjurer below L3"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Abjurer2", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer
    stats.char_level = 2
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 2)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest
    engine.apply_long_rest(bm)

    # Verify temp_hp is still 0 (no ward)
    stats = engine.get_agent_stats(bm, idx)
    assert stats.temp_hp == 0, f"Abjurer L2 should not have ward, got temp_hp={stats.temp_hp}"
    print("✅ test_arcane_ward_not_initialized_below_l3 passed")


def test_arcane_ward_not_initialized_for_other_subclass():
    """Verify Arcane Ward is NOT initialized for non-Abjurer Wizards"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Diviner3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.char_level = 3
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest
    engine.apply_long_rest(bm)

    # Verify temp_hp is still 0 (no ward for Diviner)
    stats = engine.get_agent_stats(bm, idx)
    assert stats.temp_hp == 0, f"Diviner should not have Arcane Ward, got temp_hp={stats.temp_hp}"
    print("✅ test_arcane_ward_not_initialized_for_other_subclass passed")


def test_arcane_ward_caps_at_maximum():
    """Verify Arcane Ward caps at 2 × level + INT_mod"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Abjurer6", 5, 5)
    idx = add_agent_to_battle(engine, bm, config, intel=18)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer
    stats.char_level = 6
    stats.set_class_level(rpg.CharacterClass.Wizard, 6)  # This sets spell_slots_max
    stats.restore_spell_slots()  # Populate spell_slots_remaining from max
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 6)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest to initialize ward
    engine.apply_long_rest(bm)

    stats = engine.get_agent_stats(bm, idx)
    initial_ward = stats.temp_hp
    assert initial_ward == 6, f"Initial ward should be 6, got {initial_ward}"

    # Try to manually charge with L3 slot
    # Max ward = 2 * 6 + 4 = 16
    # Manual charge with L3 slot = +6, should be 12
    success = engine.expend_arcane_ward_slot(bm, idx, 3)
    assert success, "Should successfully expend arcane ward slot"

    stats = engine.get_agent_stats(bm, idx)
    assert stats.temp_hp == 12, f"Ward should be 12 after charging with L3 slot, got {stats.temp_hp}"

    # Charge again with L2 slot (+4), should cap at 16
    success = engine.expend_arcane_ward_slot(bm, idx, 2)
    assert success, "Second charge should succeed"

    stats = engine.get_agent_stats(bm, idx)
    expected_max = 2 * 6 + 4  # 16
    assert stats.temp_hp == expected_max, f"Ward should cap at {expected_max}, got {stats.temp_hp}"
    print("✅ test_arcane_ward_caps_at_maximum passed")


def test_expend_arcane_ward_slot_success():
    """Verify expending a spell slot charges the ward"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Abjurer5", 5, 5)
    idx = add_agent_to_battle(engine, bm, config, intel=16)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer
    stats.char_level = 5
    stats.set_class_level(rpg.CharacterClass.Wizard, 5)  # This sets spell_slots_max
    stats.restore_spell_slots()  # Populate spell_slots_remaining from max
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 5)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest to initialize ward
    engine.apply_long_rest(bm)

    stats = engine.get_agent_stats(bm, idx)
    initial_ward = stats.temp_hp
    initial_slots_l2 = stats.spell_slots_remaining[1]  # L2 slots (index 1)

    # Expend a L2 slot (+4 HP)
    success = engine.expend_arcane_ward_slot(bm, idx, 2)
    assert success, "Should successfully expend arcane ward slot"

    stats = engine.get_agent_stats(bm, idx)
    expected_ward = initial_ward + 4
    assert stats.temp_hp == expected_ward, f"Ward should be {expected_ward}, got {stats.temp_hp}"
    assert stats.spell_slots_remaining[1] == initial_slots_l2 - 1, "L2 slot should be expended"
    print("✅ test_expend_arcane_ward_slot_success passed")


def test_expend_arcane_ward_slot_fails_no_slots():
    """Verify expending slot fails if no slots available"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Abjurer3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer
    stats.char_level = 3
    stats.set_class_level(rpg.CharacterClass.Wizard, 3)
    stats.restore_spell_slots()
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest to initialize ward
    engine.apply_long_rest(bm)

    # Expend all available L1 slots (L3 Wizard has 4 L1 slots)
    for _ in range(4):
        success = engine.expend_arcane_ward_slot(bm, idx, 1)
        assert success, "Should successfully expend L1 slots"

    # Try to expend another L1 slot (should fail - no slots left)
    success = engine.expend_arcane_ward_slot(bm, idx, 1)
    assert not success, "Should fail to expend arcane ward slot when none available"
    print("✅ test_expend_arcane_ward_slot_fails_no_slots passed")


def test_expend_arcane_ward_slot_fails_no_ward():
    """Verify expending slot fails if no active ward"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Abjurer3", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer
    stats.char_level = 3
    stats.temp_hp = 0  # No active ward
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    engine.set_agent_stats(bm, idx, stats)

    # Try to expend slot without active ward
    success = engine.expend_arcane_ward_slot(bm, idx, 1)
    assert not success, "Should fail to expend arcane ward slot when ward is not active"
    print("✅ test_expend_arcane_ward_slot_fails_no_ward passed")


def test_expend_arcane_ward_slot_fails_not_abjurer():
    """Verify expending slot fails for non-Abjurer Wizards"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Diviner5", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.char_level = 5
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 5)
    engine.set_agent_stats(bm, idx, stats)

    # Try to expend slot as Diviner (should fail)
    success = engine.expend_arcane_ward_slot(bm, idx, 1)
    assert not success, "Should fail to expend arcane ward slot for non-Abjurer"
    print("✅ test_expend_arcane_ward_slot_fails_not_abjurer passed")


def test_arcane_ward_multiple_charges():
    """Verify ward can be charged multiple times without exceeding cap"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Abjurer6", 5, 5)
    idx = add_agent_to_battle(engine, bm, config, intel=16)

    # Set character class and subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer
    stats.char_level = 6
    stats.set_class_level(rpg.CharacterClass.Wizard, 6)  # This sets spell_slots_max
    stats.restore_spell_slots()  # Populate spell_slots_remaining from max
    stats.initialize_class_resources(rpg.CharacterClass.Wizard, 6)
    engine.set_agent_stats(bm, idx, stats)

    # Apply long rest to initialize ward to 6
    engine.apply_long_rest(bm)

    # Max ward = 2 * 6 + 3 = 15
    # Charge with L2 slot (+4): should be 10
    success1 = engine.expend_arcane_ward_slot(bm, idx, 2)
    assert success1, "First charge should succeed"

    stats = engine.get_agent_stats(bm, idx)
    assert stats.temp_hp == 10, f"Ward should be 10 after first charge, got {stats.temp_hp}"

    # Charge with L2 slot again (+4): should be 14
    success2 = engine.expend_arcane_ward_slot(bm, idx, 2)
    assert success2, "Second charge should succeed"

    stats = engine.get_agent_stats(bm, idx)
    assert stats.temp_hp == 14, f"Ward should be 14 after second charge, got {stats.temp_hp}"

    # Charge with L1 slot (+2): should cap at 15
    success3 = engine.expend_arcane_ward_slot(bm, idx, 1)
    assert success3, "Third charge should succeed"

    stats = engine.get_agent_stats(bm, idx)
    expected_max = 15
    assert stats.temp_hp == expected_max, f"Ward should cap at {expected_max}, got {stats.temp_hp}"
    print("✅ test_arcane_ward_multiple_charges passed")


if __name__ == "__main__":
    test_arcane_ward_long_rest_initialization()
    test_arcane_ward_not_initialized_below_l3()
    test_arcane_ward_not_initialized_for_other_subclass()
    test_arcane_ward_caps_at_maximum()
    test_expend_arcane_ward_slot_success()
    test_expend_arcane_ward_slot_fails_no_slots()
    test_expend_arcane_ward_slot_fails_no_ward()
    test_expend_arcane_ward_slot_fails_not_abjurer()
    test_arcane_ward_multiple_charges()
    print("\n✅ All Arcane Ward tests passed!")
