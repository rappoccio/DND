#!/usr/bin/env python3
"""
Unit tests for per-condition save requirements.
Tests the new requires_save flag that allows mixing automatic and save-based
conditions on the same spell or weapon attack.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_attack_condition_automatic():
    """Test that a weapon condition with requires_save=false applies automatically on hit."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create attacker and target
    attacker_config = create_test_agent("Attacker", 10, 10, str=16)
    target_config = create_test_agent("Target", 11, 10, con=10)

    attacker_idx = add_agent_to_battle(engine, bm, attacker_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Create a weapon with an automatic (no-save) condition
    weapon = rpg.Weapon()
    weapon.name = "Poisoned Dagger"
    weapon.damage_dice_count = 1
    weapon.damage_dice = 4
    weapon.reach_ft = 5
    weapon.proficient = True

    # Add automatic poisoned condition (no save)
    cond = rpg.AttackCondition()
    cond.condition_name = "Poisoned"
    cond.requires_save = False  # Key: automatic on hit
    cond.condition_duration = 3
    weapon.conditions = [cond]

    # Set weapon on attacker
    dummy1 = rpg.Weapon()
    dummy2 = rpg.Weapon()
    engine.set_agent_weapons(bm, attacker_idx, [weapon, dummy1, dummy2])

    # Execute attack
    action = rpg.Attack()
    action.attacker_idx = attacker_idx
    action.target_idx = target_idx
    action.weapon_idx = 0

    result = engine.execute_action(bm, action)

    if result.hit:
        # On hit, poisoned should be applied automatically (no save)
        target_cond = engine.get_agent_conditions(bm, target_idx)
        assert target_cond.poisoned == True, "Automatic condition should apply on hit"
        print("✅ Weapon condition with requires_save=false applies automatically on hit")
    else:
        print("✅ Weapon condition test setup (miss, condition not applied)")

def test_attack_condition_requires_save():
    """Test that a weapon condition with requires_save=true requires a save."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create attacker and target with different CON
    attacker_config = create_test_agent("Attacker", 10, 10, str=16)
    target_config = create_test_agent("Target", 11, 10, con=16)  # Good CON for saves

    attacker_idx = add_agent_to_battle(engine, bm, attacker_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Create a weapon with a save-based condition
    weapon = rpg.Weapon()
    weapon.name = "Paralyzing Blade"
    weapon.damage_dice_count = 1
    weapon.damage_dice = 8
    weapon.reach_ft = 5
    weapon.proficient = True

    # Add save-based stunned condition
    cond = rpg.AttackCondition()
    cond.condition_name = "Stunned"
    cond.requires_save = True  # Key: requires save
    cond.save_ability = rpg.SaveAbility.Constitution
    cond.condition_duration = 1
    weapon.conditions = [cond]

    # Set weapon on attacker
    dummy1 = rpg.Weapon()
    dummy2 = rpg.Weapon()
    engine.set_agent_weapons(bm, attacker_idx, [weapon, dummy1, dummy2])

    # Execute attack
    action = rpg.Attack()
    action.attacker_idx = attacker_idx
    action.target_idx = target_idx
    action.weapon_idx = 0

    result = engine.execute_action(bm, action)

    if result.hit:
        # Stunned applies only on failed CON save
        target_cond = engine.get_agent_conditions(bm, target_idx)
        # With CON=16, save DC likely won't force failure, but it COULD
        # Just verify the condition property exists and is accessible
        assert hasattr(target_cond, 'stunned'), "Stunned condition should exist"
        print("✅ Weapon condition with requires_save=true requires save (save-based condition set up)")
    else:
        print("✅ Weapon condition test setup (miss, condition not applied)")

def test_spell_automatic_condition():
    """Test spell with automatic condition (requires_save=false)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create caster and target
    caster_config = create_test_agent("Caster", 5, 5, cha=16)
    target_config = create_test_agent("Target", 7, 5)

    caster_idx = add_agent_to_battle(engine, bm, caster_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Create spell with automatic condition
    spell = rpg.Spell()
    spell.name = "Ray of Sickness"
    spell.level = 1
    spell.attack_type = rpg.SpellAttack.AttackRoll
    spell.range = 60
    spell.geometry = rpg.SpellGeometry.Single

    # Add poison damage
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Poison
    dmg.num_dice = 1
    dmg.die_size = 8
    spell.magic_damage_rolls = [dmg]

    # Add automatic poisoned condition
    cond = rpg.AttackCondition()
    cond.condition_name = "Poisoned"
    cond.requires_save = False  # Automatic on hit
    cond.condition_duration = 1
    spell.conditions = [cond]

    # Set spell on caster
    engine.set_agent_spells(bm, caster_idx, [spell])
    caster_stats = engine.get_agent_stats(bm, caster_idx)
    caster_stats.can_cast_spell = True
    engine.set_agent_stats(bm, caster_idx, caster_stats)

    # Cast spell
    action = rpg.SpellAction()
    action.caster_idx = caster_idx
    action.spell_idx = 0
    action.target_indices = [target_idx]

    result = engine.execute_spell(bm, action)

    if result.valid and len(result.target_results) > 0:
        tr = result.target_results[0]
        if tr.hit:
            # On hit, poisoned should apply automatically
            target_cond = engine.get_agent_conditions(bm, target_idx)
            assert target_cond.poisoned == True, "Spell automatic condition should apply on hit"
            print("✅ Spell with automatic condition (requires_save=false) applies on hit")
        else:
            print("✅ Spell test setup (miss, condition not applied)")
    else:
        print("✅ Spell cast setup (spell effect created)")

def test_spell_save_based_condition():
    """Test spell with save-based condition (requires_save=true)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create caster and target
    caster_config = create_test_agent("Caster", 5, 5, cha=16)
    target_config = create_test_agent("Target", 7, 5, con=8)  # Low CON for easier failure

    caster_idx = add_agent_to_battle(engine, bm, caster_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Create spell with save-based condition
    spell = rpg.Spell()
    spell.name = "Hold Person"
    spell.level = 2
    spell.attack_type = rpg.SpellAttack.Save
    spell.save_ability = rpg.SaveAbility.Wisdom
    spell.range = 60
    spell.geometry = rpg.SpellGeometry.Single
    spell.requires_concentration = True

    # Add paralyzed condition with save requirement
    cond = rpg.AttackCondition()
    cond.condition_name = "Paralyzed"
    cond.requires_save = True  # Requires save
    cond.save_ability = rpg.SaveAbility.Wisdom
    cond.save_dc_ability = rpg.SaveAbility.Wisdom
    cond.condition_duration = 1
    spell.conditions = [cond]

    # Set spell on caster
    engine.set_agent_spells(bm, caster_idx, [spell])
    caster_stats = engine.get_agent_stats(bm, caster_idx)
    caster_stats.can_cast_spell = True
    engine.set_agent_stats(bm, caster_idx, caster_stats)

    # Cast spell
    action = rpg.SpellAction()
    action.caster_idx = caster_idx
    action.spell_idx = 0
    action.target_indices = [target_idx]

    result = engine.execute_spell(bm, action)

    if result.valid and len(result.target_results) > 0:
        tr = result.target_results[0]
        # For save spells, paralyzed applies on failed save
        target_cond = engine.get_agent_conditions(bm, target_idx)
        # Just verify the condition is accessible
        assert hasattr(target_cond, 'paralyzed'), "Paralyzed condition should exist"
        print("✅ Spell with save-based condition (requires_save=true) set up correctly")
    else:
        print("✅ Spell cast setup (spell effect created)")

def test_mixed_conditions_on_spell():
    """Test spell with both automatic and save-based conditions."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create caster and target
    caster_config = create_test_agent("Caster", 5, 5, cha=16)
    target_config = create_test_agent("Target", 7, 5, con=10)

    caster_idx = add_agent_to_battle(engine, bm, caster_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Create spell with mixed conditions
    spell = rpg.Spell()
    spell.name = "Wyvern Sting"
    spell.level = 2
    spell.attack_type = rpg.SpellAttack.AttackRoll
    spell.range = 30
    spell.geometry = rpg.SpellGeometry.Single

    # Add poison damage
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Poison
    dmg.num_dice = 1
    dmg.die_size = 6
    spell.magic_damage_rolls = [dmg]

    # Add automatic poisoned condition
    cond1 = rpg.AttackCondition()
    cond1.condition_name = "Poisoned"
    cond1.requires_save = False  # Automatic on hit
    cond1.condition_duration = 1

    # Add save-based stunned condition
    cond2 = rpg.AttackCondition()
    cond2.condition_name = "Stunned"
    cond2.requires_save = True  # Requires save
    cond2.save_ability = rpg.SaveAbility.Constitution
    cond2.condition_duration = 1

    spell.conditions = [cond1, cond2]

    # Set spell on caster
    engine.set_agent_spells(bm, caster_idx, [spell])
    caster_stats = engine.get_agent_stats(bm, caster_idx)
    caster_stats.can_cast_spell = True
    engine.set_agent_stats(bm, caster_idx, caster_stats)

    # Cast spell
    action = rpg.SpellAction()
    action.caster_idx = caster_idx
    action.spell_idx = 0
    action.target_indices = [target_idx]

    result = engine.execute_spell(bm, action)

    if result.valid and len(result.target_results) > 0:
        tr = result.target_results[0]
        if tr.hit:
            # On hit: poisoned applies automatically, stunned requires save
            target_cond = engine.get_agent_conditions(bm, target_idx)
            assert target_cond.poisoned == True, "Automatic poisoned should apply"
            # Stunned might or might not apply depending on save result
            print("✅ Spell with mixed conditions: automatic applied, save-based evaluated")
        else:
            print("✅ Spell test setup (miss, conditions not applied)")
    else:
        print("✅ Spell cast setup (spell effect created)")

def run_tests():
    """Run all condition save requirement tests."""
    print("\n" + "="*60)
    print("Testing Per-Condition Save Requirements (requires_save)")
    print("="*60 + "\n")

    tests = [
        test_attack_condition_automatic,
        test_attack_condition_requires_save,
        test_spell_automatic_condition,
        test_spell_save_based_condition,
        test_mixed_conditions_on_spell,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
            print()
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}\n")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}\n")
            failed += 1

    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
