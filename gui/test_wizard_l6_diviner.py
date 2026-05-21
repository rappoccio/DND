#!/usr/bin/env python3
"""
Test Wizard L6 Diviner mechanics: Expert Divination
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_expert_divination_restores_slot():
    """Verify Expert Divination restores a lower-level spell slot"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Diviner wizard at L6
    config_wizard = create_test_agent("DivinierWizard6", 5, 5)
    idx_wizard = add_agent_to_battle(engine, bm, config_wizard)

    stats = engine.get_agent_stats(bm, idx_wizard)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 6
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.intel = 16
    stats.set_class_level(rpg.CharacterClass.Wizard, 6)
    engine.set_agent_stats(bm, idx_wizard, stats)

    # Create a divination spell (we'll manually set its school)
    divination_spell = rpg.Spell()
    divination_spell.name = "Identify"
    divination_spell.level = 1
    divination_spell.school = rpg.SpellSchool.Divination
    divination_spell.geometry = rpg.SpellGeometry.Single
    divination_spell.attack_type = rpg.SpellAttack.Automatic
    divination_spell.range = 0

    # Set spell for wizard
    engine.set_agent_spells(bm, idx_wizard, [divination_spell])

    # Get initial spell slots
    stats = engine.get_agent_stats(bm, idx_wizard)
    initial_l1_slots = stats.spell_slots_remaining[0]  # L1 slots
    initial_l2_slots = stats.spell_slots_remaining[1]  # L2 slots

    # Cast L2 Divination spell (should restore L1 slot if one is expended)
    # First, expend a L1 slot manually to test restoration
    stats.spell_slots_remaining[0] = max(0, stats.spell_slots_remaining[0] - 1)
    engine.set_agent_stats(bm, idx_wizard, stats)

    # Create target
    config_target = create_test_agent("Target", 6, 5)
    idx_target = add_agent_to_battle(engine, bm, config_target)

    # Now cast the L2 Divination spell
    spell_action = rpg.SpellAction()
    spell_action.caster_idx = idx_wizard
    spell_action.spell_idx = 0
    spell_action.slot_level = 2
    spell_action.target_indices = [idx_target]
    spell_action.aoe_col = 0
    spell_action.aoe_row = 0

    result = engine.execute_spell(bm, spell_action)

    # Check that L1 slot was restored
    stats_after = engine.get_agent_stats(bm, idx_wizard)
    assert stats_after.spell_slots_remaining[0] > 0, \
        "Expert Divination should have restored a L1 spell slot"
    print("✅ test_expert_divination_restores_slot passed")


def test_expert_divination_only_divination_spells():
    """Verify Expert Divination only works with Divination spells"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Diviner wizard
    config_wizard = create_test_agent("DivinierWizard6", 5, 5)
    idx_wizard = add_agent_to_battle(engine, bm, config_wizard)

    stats = engine.get_agent_stats(bm, idx_wizard)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 6
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.intel = 16
    stats.set_class_level(rpg.CharacterClass.Wizard, 6)
    engine.set_agent_stats(bm, idx_wizard, stats)

    # Create an EVOCATION spell (not Divination)
    evocation_spell = rpg.Spell()
    evocation_spell.name = "Fireball"
    evocation_spell.level = 3
    evocation_spell.school = rpg.SpellSchool.Evocation  # NOT Divination
    evocation_spell.geometry = rpg.SpellGeometry.Sphere
    evocation_spell.attack_type = rpg.SpellAttack.Save
    evocation_spell.save_ability = rpg.SaveAbility.Dexterity
    evocation_spell.range = 150
    evocation_spell.radius = 20

    engine.set_agent_spells(bm, idx_wizard, [evocation_spell])

    # Get initial slots
    stats = engine.get_agent_stats(bm, idx_wizard)
    initial_l3_slots = stats.spell_slots_remaining[2]  # L3 slots

    # Cast L3 Evocation spell
    config_target = create_test_agent("Target", 7, 5)
    idx_target = add_agent_to_battle(engine, bm, config_target)

    spell_action = rpg.SpellAction()
    spell_action.caster_idx = idx_wizard
    spell_action.spell_idx = 0
    spell_action.slot_level = 3
    spell_action.target_indices = [idx_target]
    spell_action.aoe_col = 6
    spell_action.aoe_row = 5

    result = engine.execute_spell(bm, spell_action)

    # Check that no L1/L2 slots were restored (since it's not Divination)
    stats_after = engine.get_agent_stats(bm, idx_wizard)
    assert stats_after.spell_slots_remaining[0] == stats.spell_slots_remaining[0], \
        "Expert Divination should not restore slots for non-Divination spells"
    print("✅ test_expert_divination_only_divination_spells passed")


def test_expert_divination_only_diviner_subclass():
    """Verify Expert Divination only works for Diviner subclass"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create non-Diviner wizard (Abjurer)
    config_wizard = create_test_agent("AbjurerWizard6", 5, 5)
    idx_wizard = add_agent_to_battle(engine, bm, config_wizard)

    stats = engine.get_agent_stats(bm, idx_wizard)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 6
    stats.wizard_subclass = rpg.WizardSubclass.Abjurer  # NOT Diviner
    stats.intel = 16
    stats.set_class_level(rpg.CharacterClass.Wizard, 6)
    engine.set_agent_stats(bm, idx_wizard, stats)

    # Create a Divination spell
    divination_spell = rpg.Spell()
    divination_spell.name = "Identify"
    divination_spell.level = 1
    divination_spell.school = rpg.SpellSchool.Divination
    divination_spell.geometry = rpg.SpellGeometry.Single
    divination_spell.attack_type = rpg.SpellAttack.Automatic
    divination_spell.range = 0

    engine.set_agent_spells(bm, idx_wizard, [divination_spell])

    # Get initial slots
    stats = engine.get_agent_stats(bm, idx_wizard)
    initial_l1_slots = stats.spell_slots_remaining[0]

    # Cast L2 Divination spell
    config_target = create_test_agent("Target", 6, 5)
    idx_target = add_agent_to_battle(engine, bm, config_target)

    spell_action = rpg.SpellAction()
    spell_action.caster_idx = idx_wizard
    spell_action.spell_idx = 0
    spell_action.slot_level = 2
    spell_action.target_indices = [idx_target]
    spell_action.aoe_col = 0
    spell_action.aoe_row = 0

    result = engine.execute_spell(bm, spell_action)

    # Check that no slots were restored (since it's not Diviner subclass)
    stats_after = engine.get_agent_stats(bm, idx_wizard)
    assert stats_after.spell_slots_remaining[0] == initial_l1_slots, \
        "Expert Divination should not work for non-Diviner wizards"
    print("✅ test_expert_divination_only_diviner_subclass passed")


def test_expert_divination_requires_l2_plus_slot():
    """Verify Expert Divination only works with L2+ slots"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Diviner wizard
    config_wizard = create_test_agent("DivinierWizard6", 5, 5)
    idx_wizard = add_agent_to_battle(engine, bm, config_wizard)

    stats = engine.get_agent_stats(bm, idx_wizard)
    stats.character_class = rpg.CharacterClass.Wizard
    stats.char_level = 6
    stats.wizard_subclass = rpg.WizardSubclass.Diviner
    stats.intel = 16
    stats.set_class_level(rpg.CharacterClass.Wizard, 6)
    engine.set_agent_stats(bm, idx_wizard, stats)

    # Create a cantrip (no slot used)
    cantrip = rpg.Spell()
    cantrip.name = "Mage Hand"
    cantrip.level = 0  # Cantrip
    cantrip.school = rpg.SpellSchool.Divination
    cantrip.geometry = rpg.SpellGeometry.Single
    cantrip.attack_type = rpg.SpellAttack.Automatic
    cantrip.range = 30

    engine.set_agent_spells(bm, idx_wizard, [cantrip])

    # Get initial slots
    stats = engine.get_agent_stats(bm, idx_wizard)
    initial_slots = list(stats.spell_slots_remaining)

    # Cast cantrip
    config_target = create_test_agent("Target", 6, 5)
    idx_target = add_agent_to_battle(engine, bm, config_target)

    spell_action = rpg.SpellAction()
    spell_action.caster_idx = idx_wizard
    spell_action.spell_idx = 0
    spell_action.slot_level = 0  # Cantrip, no slot
    spell_action.target_indices = [idx_target]
    spell_action.aoe_col = 0
    spell_action.aoe_row = 0

    result = engine.execute_spell(bm, spell_action)

    # Check that no slots were restored
    stats_after = engine.get_agent_stats(bm, idx_wizard)
    for i in range(9):
        assert stats_after.spell_slots_remaining[i] == initial_slots[i], \
            f"Expert Divination should not work with cantrips (L0 slots)"
    print("✅ test_expert_divination_requires_l2_plus_slot passed")


if __name__ == "__main__":
    tests = [
        test_expert_divination_restores_slot,
        test_expert_divination_only_divination_spells,
        test_expert_divination_only_diviner_subclass,
        test_expert_divination_requires_l2_plus_slot,
    ]

    print("Running Wizard L6 Diviner Tests...")
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
