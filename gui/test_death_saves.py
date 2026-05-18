#!/usr/bin/env python3
"""
Unit tests for death save mechanics, specifically melee auto-crit handling.
Tests that melee hits within 5ft on unconscious targets apply 2 death save
failures and do NOT roll an additional death save.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_melee_autocrit_death_save():
    """
    Test that melee auto-crit on unconscious target applies 2 death save
    failures and does NOT roll an additional death save.

    Setup:
    - Attacker at (10, 10) with rapier (melee)
    - Target at (11, 10) with 10 HP (one cell away = within 5ft)

    Flow:
    1. Knock target unconscious manually
    2. Attack with melee weapon within 5ft
    3. Verify: auto-crit triggers, 2 death saves applied, no additional roll
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create attacker and target close together
    attacker_config = create_test_agent("Attacker", 10, 10, str=16, dex=10)
    target_config = create_test_agent("Target", 11, 10, hp=10)

    attacker_idx = add_agent_to_battle(engine, bm, attacker_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Knock target unconscious manually (don't kill yet)
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = target_idx
    cond.caster_idx = attacker_idx
    cond.condition_name = "Unconscious"
    cond.turns_remaining = 10
    engine.add_agent_condition(bm, cond)

    # Verify target is unconscious
    target_cond = engine.get_agent_conditions(bm, target_idx)
    assert target_cond.unconscious == True
    assert target_cond.death_save_successes == 0
    assert target_cond.death_save_failures == 0
    print("✓ Target knocked unconscious")

    # Attack with melee weapon (rapier = first weapon)
    action = rpg.AttackAction()
    action.attacker_idx = attacker_idx
    action.target_idx = target_idx
    action.weapon_idx = 0  # rapier is index 0

    result = engine.execute_attack(bm, action)

    # Verify auto-crit was triggered
    assert result.critical == True, "Expected auto-crit for melee hit on unconscious target"
    print("✓ Auto-crit triggered")

    # Check death save state after attack
    target_cond_after = engine.get_agent_conditions(bm, target_idx)

    # Should have exactly 2 death save failures from auto-crit
    # NOT 3 (which would indicate an additional death save roll was made)
    assert target_cond_after.death_save_failures == 2, \
        f"Expected 2 death save failures, got {target_cond_after.death_save_failures}"
    assert target_cond_after.death_save_successes == 0, \
        f"Expected 0 successes, got {target_cond_after.death_save_successes}"
    print("✓ Exactly 2 death save failures applied (no additional roll)")

    # Target should still be unconscious but not dead yet (needs 3 failures)
    assert target_cond_after.unconscious == True
    assert target_cond_after.dead == False
    print("✓ Target unconscious but not dead")

def test_melee_autocrit_kills_on_third_failure():
    """
    Test that melee auto-crit on unconscious target with 1 existing failure
    results in death (3 total failures).
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create attacker and target
    attacker_config = create_test_agent("Attacker", 10, 10, str=16)
    target_config = create_test_agent("Target", 11, 10, hp=1)

    attacker_idx = add_agent_to_battle(engine, bm, attacker_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Knock target unconscious with 1 failure already
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = target_idx
    cond.caster_idx = attacker_idx
    cond.condition_name = "Unconscious"
    cond.turns_remaining = 10
    engine.add_agent_condition(bm, cond)

    # Manually add 1 death save failure
    target_cond = engine.get_agent_conditions(bm, target_idx)
    target_cond.death_save_failures = 1
    engine.set_agent_conditions(bm, target_idx, target_cond)

    print(f"Initial state: {target_cond.death_save_failures}/3 failures")

    # Attack with melee weapon within 5ft
    action = rpg.AttackAction()
    action.attacker_idx = attacker_idx
    action.target_idx = target_idx
    action.weapon_idx = 0  # rapier

    result = engine.execute_attack(bm, action)

    # Should have 3 failures total: 1 + 2 from auto-crit = dead
    target_cond_after = engine.get_agent_conditions(bm, target_idx)
    assert target_cond_after.death_save_failures == 3, \
        f"Expected 3 failures, got {target_cond_after.death_save_failures}"
    assert target_cond_after.dead == True, "Expected target to be dead"
    print("✓ 3 failures triggered death (1 existing + 2 from auto-crit)")

def test_ranged_attack_no_autocrit():
    """
    Test that ranged attacks do NOT trigger auto-crit on unconscious targets.
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create attacker and target (far apart for ranged)
    attacker_config = create_test_agent("Archer", 5, 5, dex=16)
    target_config = create_test_agent("Target", 15, 5, hp=10)

    attacker_idx = add_agent_to_battle(engine, bm, attacker_config)
    target_idx = add_agent_to_battle(engine, bm, target_config)

    # Knock target unconscious
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = target_idx
    cond.caster_idx = attacker_idx
    cond.condition_name = "Unconscious"
    cond.turns_remaining = 10
    engine.add_agent_condition(bm, cond)

    # Attack with ranged weapon
    action = rpg.AttackAction()
    action.attacker_idx = attacker_idx
    action.target_idx = target_idx
    action.weapon_idx = 2  # longbow is index 2

    result = engine.execute_attack(bm, action)

    # Ranged attacks should NOT auto-crit
    assert result.critical == False, "Ranged attacks should not auto-crit"
    print("✓ Ranged attack did not auto-crit")

    # Should not have death save failures applied
    target_cond_after = engine.get_agent_conditions(bm, target_idx)
    assert target_cond_after.death_save_failures == 0, \
        "Ranged attack should not apply death save failures"
    print("✓ No automatic death save failures from ranged attack")

def run_tests():
    """Run all death save tests."""
    print("\n" + "="*60)
    print("Testing Death Save Mechanics (Melee Auto-Crit)")
    print("="*60 + "\n")

    tests = [
        test_melee_autocrit_death_save,
        test_melee_autocrit_kills_on_third_failure,
        test_ranged_attack_no_autocrit,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
            print()
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}\n")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}\n")
            failed += 1

    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
